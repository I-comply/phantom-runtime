from sqlalchemy.orm import Session
from app.core.models import Event
from app.core.models_v2 import DeFiEvent, AsyncJob
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
        
        # Create core event first
        payload = {
            "asset": asset,
            "amount": amount,
            "price": price,
            **(metadata or {})
        }
        
        core_event = Event(
            entity_id=entity_id,
            event_type=event_type,
            payload=payload
        )
        db.add(core_event)
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
    def get_entity_portfolio(db: Session, entity_id: str) -> Dict[str, Any]:
        """Get portfolio summary for an entity"""
        defi_events = db.query(DeFiEvent).filter(
            DeFiEvent.entity_id == entity_id
        ).order_by(DeFiEvent.created_at.asc()).all()
        
        balances = {}
        transactions = []
        
        for event in defi_events:
            asset = event.asset
            amount = float(event.amount)
            
            if event.event_type == "deposit":
                balances[asset] = balances.get(asset, 0) + amount
            elif event.event_type == "withdraw":
                balances[asset] = balances.get(asset, 0) - amount
            elif event.event_type == "trade":
                # Handle trade event_metadata
                from_asset = event.event_metadata.get("from_asset")
                to_asset = event.event_metadata.get("to_asset")
                from_amount = float(event.event_metadata.get("from_amount", 0))
                to_amount = float(event.event_metadata.get("to_amount", 0))
                
                if from_asset:
                    balances[from_asset] = balances.get(from_asset, 0) - from_amount
                if to_asset:
                    balances[to_asset] = balances.get(to_asset, 0) + to_amount
            
            transactions.append({
                "type": event.event_type,
                "asset": asset,
                "amount": amount,
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
