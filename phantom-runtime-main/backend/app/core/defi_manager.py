from sqlalchemy.orm import Session
from app.core.models import Event
from app.core.models_v2 import DeFiEvent, AsyncJob
from app.core.event_store import EventStore
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import uuid
import logging

logger = logging.getLogger(__name__)

class DeFiEventManager:
    """Manage DeFi-specific events (fork-ready, not active trading)"""
    
    SUPPORTED_EVENT_TYPES = [
        "deposit", "withdraw", "trade", "transfer",
        "stake", "unstake", "claim_rewards"
    ]
    
    @staticmethod
    def create_defi_event(
        db: Session,
        entity_id: str,
        event_type: str,
        asset: str,
        amount: str,
        price: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        workspace_id: Optional[str] = None
    ) -> DeFiEvent:
        """Create a DeFi event and corresponding core event"""
        
        if event_type not in DeFiEventManager.SUPPORTED_EVENT_TYPES:
            raise ValueError(f"Unsupported DeFi event type: {event_type}")
        
        # Strict, exact amounts (ValueError -> 400): a bad amount used to be stored and then made
        # every later replay of the entity fail.
        from app.core import money
        parsed = money.parse_amount(amount)
        if price is not None:
            money.parse_amount(price)
        try:
            money.validate_money_payload(event_type, metadata or {})  # e.g. trade from_amount/to_amount
        except money.AmountError as e:
            raise ValueError(str(e))

        # Create core event first. Caller metadata comes first so it can't override the real fields.
        payload = {
            **(metadata or {}),
            "asset": asset,
            "amount": money.fmt(parsed),
            "price": price,
        }
        
        EventStore.lock_entity(db, entity_id)
        core_event = Event(
            entity_id=entity_id,
            event_type=event_type,
            payload=payload
        )
        db.add(core_event)
        # This bypasses EventStore.append_event (needs the flushed core_event.id
        # below before DeFiEvent can be created), so claim the entity->workspace
        # link here too — otherwise a DeFi-only entity_id never gets linked and
        # the v1 event/state/snapshot endpoints 404 it even for its own creator.
        EventStore.claim_entity(db, entity_id, workspace_id)
        db.flush()  # Get ID without committing

        # Create DeFi event
        defi_event = DeFiEvent(
            workspace_id=workspace_id,
            entity_id=entity_id,
            event_type=event_type,
            asset=asset,
            amount=amount,
            price=price,
            event_metadata=metadata or {},  # Use event_metadata field
            core_event_id=core_event.id
        )
        db.add(defi_event)
        db.commit()
        db.refresh(defi_event)
        
        logger.info(f"Created DeFi {event_type} event for {entity_id}: {amount} {asset}")
        return defi_event
    
    @staticmethod
    def get_entity_portfolio(db: Session, entity_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        """Get portfolio summary for an entity. workspace_id=None means unscoped
        (admin/internal callers only); route handlers must pass the caller's own
        workspace_id for non-admin keys."""
        q = db.query(DeFiEvent).filter(DeFiEvent.entity_id == entity_id)
        if workspace_id is not None:
            q = q.filter(DeFiEvent.workspace_id == workspace_id)
        defi_events = q.order_by(DeFiEvent.created_at.asc()).all()
        
        # Exact decimal arithmetic; balances and amounts are canonical decimal strings.
        from app.core import money
        balances = {}
        transactions = []

        def bal(asset):
            return money.lenient(balances.get(asset, 0))

        for event in defi_events:
            asset = event.asset
            amount = money.lenient(event.amount)

            if event.event_type in ("deposit", "claim_rewards"):
                balances[asset] = money.fmt(money.add(bal(asset), amount))
            elif event.event_type in ("withdraw", "transfer"):
                balances[asset] = money.fmt(money.sub(bal(asset), amount))
            elif event.event_type == "trade":
                # Handle trade event_metadata
                meta = event.event_metadata or {}
                from_asset = meta.get("from_asset")
                to_asset = meta.get("to_asset")
                from_amount = money.lenient(meta.get("from_amount", 0))
                to_amount = money.lenient(meta.get("to_amount", 0))

                if from_asset:
                    balances[from_asset] = money.fmt(money.sub(bal(from_asset), from_amount))
                if to_asset:
                    balances[to_asset] = money.fmt(money.add(bal(to_asset), to_amount))

            transactions.append({
                "type": event.event_type,
                "asset": asset,
                "amount": money.fmt(amount),
                "price": event.price,
                "timestamp": event.created_at.isoformat()
            })

        return {
            "entity_id": entity_id,
            "balances": balances,
            "transaction_count": len(transactions),
            "recent_transactions": transactions[-10:]
        }

class AsyncPipeline:
    """Async event ingestion pipeline"""
    
    @staticmethod
    def create_batch_job(db: Session, events_data: list) -> AsyncJob:
        """Create async job for batch event ingestion"""
        job = AsyncJob(
            job_type="event_batch",
            status="pending",
            payload={"events": events_data}
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    
    @staticmethod
    def process_batch_job(db: Session, job_id: str) -> AsyncJob:
        """Process a batch ingestion job"""
        job = db.query(AsyncJob).filter(AsyncJob.id == job_id).first()
        
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        job.status = "processing"
        db.commit()
        
        try:
            events_data = job.payload.get("events", [])
            created_events = []
            
            # Lock every touched entity in a fixed order (no deadlock between two batches) before
            # inserting, so the batch's events commit in id order with respect to snapshots.
            for locked_entity in sorted({e["entity_id"] for e in events_data}):
                EventStore.lock_entity(db, locked_entity)

            for event_data in events_data:
                event = Event(
                    entity_id=event_data["entity_id"],
                    event_type=event_data["event_type"],
                    payload=event_data["payload"]
                )
                db.add(event)
                created_events.append(event.id)
            
            db.commit()
            
            job.status = "completed"
            job.result = {"created_count": len(created_events)}
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            
            logger.info(f"Batch job {job_id} completed: {len(created_events)} events created")
            return job
            
        except Exception as e:
            logger.error(f"Batch job {job_id} failed: {e}")
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            raise
