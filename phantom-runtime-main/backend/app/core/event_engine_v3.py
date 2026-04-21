from sqlalchemy.orm import Session
from app.core.models_v3 import EventV3, EventQueue
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import asyncio
import logging
import hashlib
import json

logger = logging.getLogger(__name__)

class EventEngineV3:
    """Hardened event engine with chaining and async pipeline"""
    
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
    def get_entity_chain(db: Session, entity_id: str) -> List[EventV3]:
        """Get complete event chain for entity"""
        return db.query(EventV3).filter(
            EventV3.entity_id == entity_id
        ).order_by(EventV3.block_index.asc()).all()
    
    @staticmethod
    def verify_chain_integrity(db: Session, entity_id: str) -> bool:
        """Verify hash chain integrity"""
        events = EventEngineV3.get_entity_chain(db, entity_id)
        
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
    """Async event ingestion pipeline"""
    
    @staticmethod
    def queue_event(
        db: Session,
        entity_id: str,
        event_data: Dict[str, Any],
        priority: str = 'normal'
    ) -> EventQueue:
        """Add event to async queue"""
        queue_item = EventQueue(
            entity_id=entity_id,
            event_data=event_data,
            priority=priority,
            status='pending'
        )
        db.add(queue_item)
        db.commit()
        db.refresh(queue_item)
        return queue_item
    
    @staticmethod
    def process_queue_batch(db: Session, batch_size: int = 100) -> int:
        """Process batch of queued events"""
        queued = db.query(EventQueue).filter(
            EventQueue.status == 'pending'
        ).order_by(
            EventQueue.priority.desc(),
            EventQueue.created_at.asc()
        ).limit(batch_size).all()
        
        processed_count = 0
        
        for item in queued:
            try:
                item.status = 'processing'
                db.commit()
                
                # Create event
                event_data = item.event_data
                EventEngineV3.create_event(
                    db=db,
                    entity_id=item.entity_id,
                    event_type=event_data['event_type'],
                    payload=event_data['payload'],
                    tenant_id=event_data.get('tenant_id'),
                    priority=item.priority,
                    source=event_data.get('source', 'api')
                )
                
                item.status = 'completed'
                item.processed_at = datetime.now(timezone.utc)
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Queue processing error: {e}")
                item.status = 'failed'
                item.error = str(e)
                item.retry_count += 1
            
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
