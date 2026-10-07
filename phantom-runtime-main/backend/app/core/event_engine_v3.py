from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.models_v3 import EventV3, EventQueue
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import hashlib
import json

logger = logging.getLogger(__name__)

class EventEngineV3:
    """Event chaining (corruption/reordering detection, not tamper-evident —
    see EventV3's docstring) and an async ingestion pipeline."""
    
    @staticmethod
    def create_event(
        db: Session,
        entity_id: str,
        event_type: str,
        payload: Dict[str, Any],
        tenant_id: Optional[str] = None,
        priority: str = 'normal',
        source: str = 'api',
        created_by: Optional[str] = None,
        hmac_signature: Optional[str] = None,
        nonce: Optional[str] = None
    ) -> EventV3:
        """Create a new event with hash chaining"""
        
        # Serialize writers of this entity's chain until commit. Without it two writers read the same
        # last block and both append block N+1 (a forked chain; verify_chain_integrity then fails).
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": "events_v3:" + entity_id})

        # Get last event for this entity to chain
        last_event = db.query(EventV3).filter(
            EventV3.entity_id == entity_id
        ).order_by(EventV3.block_index.desc()).first()
        
        block_index = (last_event.block_index + 1) if last_event else 0
        previous_hash = last_event.event_hash if last_event else None
        
        # Compute event hash
        event_hash = EventV3.compute_hash(
            entity_id, event_type, payload, block_index, previous_hash
        )
        
        # Check for duplicate
        existing = db.query(EventV3).filter(EventV3.event_hash == event_hash).first()
        if existing:
            logger.warning(f"Duplicate event detected: {event_hash}")
            return existing
        
        # Create event
        event = EventV3(
            entity_id=entity_id,
            event_type=event_type,
            payload=payload,
            event_hash=event_hash,
            previous_hash=previous_hash,
            block_index=block_index,
            tenant_id=tenant_id,
            priority_level=priority,
            source=source,
            created_by=created_by,
            hmac_signature=hmac_signature,
            nonce=nonce
        )
        
        db.add(event)
        db.commit()
        db.refresh(event)
        
        logger.info(f"Event created: {event_hash[:16]}... (block {block_index})")
        return event
    
    @staticmethod
    def get_entity_chain(db: Session, entity_id: str, tenant_id: Optional[str] = None) -> List[EventV3]:
        """Get complete event chain for entity. tenant_id=None means unscoped
        (admin / internal callers only — see routes_v3.py for the caller-side gate);
        route handlers must pass the caller's own tenant_id for non-admin keys."""
        q = db.query(EventV3).filter(EventV3.entity_id == entity_id)
        if tenant_id is not None:
            q = q.filter(EventV3.tenant_id == tenant_id)
        return q.order_by(EventV3.block_index.asc()).all()

    @staticmethod
    def verify_chain_integrity(db: Session, entity_id: str, tenant_id: Optional[str] = None) -> bool:
        """Recompute and check the unkeyed chain hash — detects corruption or
        reordering, not forgery by anyone with write access to events_v3
        (that hash is recomputable from public fields alone). Does not check
        hmac_signature/nonce; neither column is verified anywhere yet."""
        events = EventEngineV3.get_entity_chain(db, entity_id, tenant_id)
        
        for i, event in enumerate(events):
            # Recompute hash
            expected_hash = EventV3.compute_hash(
                event.entity_id,
                event.event_type,
                event.payload,
                event.block_index,
                event.previous_hash
            )
            
            if event.event_hash != expected_hash:
                logger.error(f"Hash mismatch at block {event.block_index}")
                return False
            
            # Check chain linkage
            if i > 0:
                if event.previous_hash != events[i-1].event_hash:
                    logger.error(f"Chain broken at block {event.block_index}")
                    return False
        
        return True

class AsyncEventPipeline:
    """Async event ingestion pipeline.

    Queue items carry their tenant in event_data["tenant_id"] (the queue table has no tenant column).
    A claimed item records event_data["_claimed_at"]; an item stuck in 'processing' longer than
    CLAIM_LEASE_S (the worker died) goes back to 'pending'. Events written from the queue are tagged
    created_by="queue:<item id>", so a recovered item whose event already exists is completed instead
    of written twice. Failures retry up to MAX_RETRIES, then stay 'failed'."""

    MAX_RETRIES = 3
    CLAIM_LEASE_S = 300

    @staticmethod
    def queue_event(
        db: Session,
        entity_id: str,
        event_data: Dict[str, Any],
        priority: str = 'normal',
        tenant_id: Optional[str] = None
    ) -> EventQueue:
        """Add event to async queue. tenant_id (the caller's workspace) is stored with the item."""
        data = dict(event_data)
        if tenant_id is not None:
            data["tenant_id"] = str(tenant_id)
        queue_item = EventQueue(
            entity_id=entity_id,
            event_data=data,
            priority=priority,
            status='pending'
        )
        db.add(queue_item)
        db.commit()
        db.refresh(queue_item)
        return queue_item

    @staticmethod
    def _recover_stale(db: Session, tenant_id: Optional[str]) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=AsyncEventPipeline.CLAIM_LEASE_S)
        q = db.query(EventQueue).filter(EventQueue.status == 'processing')
        if tenant_id is not None:
            q = q.filter(EventQueue.event_data['tenant_id'].astext == str(tenant_id))
        for item in q.with_for_update(skip_locked=True).all():
            claimed = (item.event_data or {}).get("_claimed_at")
            try:
                stale = claimed is None or datetime.fromisoformat(claimed) < cutoff
            except ValueError:
                stale = True
            if stale:
                item.status = 'pending'
                item.retry_count = (item.retry_count or 0) + 1
        db.commit()

    @staticmethod
    def process_queue_batch(db: Session, batch_size: int = 100, tenant_id: Optional[str] = None) -> int:
        """Process a batch of queued events. tenant_id=None processes every tenant's items (admin /
        internal callers only); otherwise only that tenant's items are touched."""
        AsyncEventPipeline._recover_stale(db, tenant_id)
        q = db.query(EventQueue).filter(EventQueue.status == 'pending')
        if tenant_id is not None:
            q = q.filter(EventQueue.event_data['tenant_id'].astext == str(tenant_id))
        queued = q.order_by(
            EventQueue.priority.desc(),
            EventQueue.created_at.asc()
        ).limit(batch_size).with_for_update(skip_locked=True).all()
        
        processed_count = 0
        
        for item in queued:
            try:
                event_data = dict(item.event_data)
                item.status = 'processing'
                item.event_data = dict(event_data, _claimed_at=datetime.now(timezone.utc).isoformat())
                db.commit()
                
                tag = f"queue:{item.id}"
                already = db.query(EventV3).filter(
                    EventV3.entity_id == item.entity_id, EventV3.created_by == tag).first()
                if already is None:
                    EventEngineV3.create_event(
                        db=db,
                        entity_id=item.entity_id,
                        event_type=event_data['event_type'],
                        payload=event_data['payload'],
                        tenant_id=event_data.get('tenant_id'),
                        priority=item.priority,
                        source=event_data.get('source', 'api'),
                        created_by=tag
                    )
                
                item.status = 'completed'
                item.processed_at = datetime.now(timezone.utc)
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Queue processing error: {e}")
                db.rollback()  # a failed insert leaves the session unusable until rolled back
                item = db.query(EventQueue).filter(EventQueue.id == item.id).one()
                item.retry_count = (item.retry_count or 0) + 1
                item.error = str(e)[:500]
                item.status = 'failed' if item.retry_count >= AsyncEventPipeline.MAX_RETRIES else 'pending'
            
            db.commit()
        
        return processed_count
    
    @staticmethod
    def cleanup_old_queue_items(db: Session, hours: int = 24):
        """Clean up completed/failed queue items"""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        db.query(EventQueue).filter(
            EventQueue.status.in_(['completed', 'failed']),
            EventQueue.processed_at < cutoff
        ).delete()
        db.commit()
