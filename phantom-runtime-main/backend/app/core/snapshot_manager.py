from sqlalchemy.orm import Session
from app.core.models import Event
from app.core.models_v2 import Snapshot
from app.core.reconstructor import StateReconstructor
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

class SnapshotManager:
    SNAPSHOT_INTERVAL = 100  # Create snapshot every N events
    
    @staticmethod
    def should_create_snapshot(db: Session, entity_id: str, workspace_id: Optional[str] = None) -> bool:
        """Check if a new snapshot should be created"""
        # Get latest snapshot
        latest_snapshot = db.query(Snapshot).filter(
            Snapshot.entity_id == entity_id
        ).order_by(Snapshot.snapshot_number.desc()).first()
        
        if not latest_snapshot:
            # Create first snapshot if entity has enough events
            event_count = db.query(Event).filter(Event.entity_id == entity_id).count()
            return event_count >= SnapshotManager.SNAPSHOT_INTERVAL
        
        # Check events since last snapshot
        events_since = db.query(Event).filter(
            Event.entity_id == entity_id,
            Event.id > latest_snapshot.last_event_id
        ).count()
        
        return events_since >= SnapshotManager.SNAPSHOT_INTERVAL
    
    @staticmethod
    def create_snapshot(db: Session, entity_id: str, workspace_id: Optional[str] = None) -> Optional[Snapshot]:
        """Create a new snapshot for an entity"""
        try:
            # Get all events for reconstruction
            events = db.query(Event).filter(
                Event.entity_id == entity_id
            ).order_by(Event.created_at.asc()).all()
            
            if not events:
                logger.warning(f"No events found for entity {entity_id}")
                return None
            
            # Reconstruct full state
            state = StateReconstructor.reconstruct(events)
            
            # Get latest snapshot number
            latest_snapshot = db.query(Snapshot).filter(
                Snapshot.entity_id == entity_id
            ).order_by(Snapshot.snapshot_number.desc()).first()
            
            snapshot_number = (latest_snapshot.snapshot_number + 1) if latest_snapshot else 1
            
            # Create snapshot
            snapshot = Snapshot(
                entity_id=entity_id,
                workspace_id=workspace_id,
                snapshot_number=snapshot_number,
                event_count=len(events),
                last_event_id=events[-1].id,
                state_data=state,
                created_at=datetime.now(timezone.utc)
            )
            
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
            
            logger.info(f"Created snapshot #{snapshot_number} for entity {entity_id} at event {events[-1].id}")
            return snapshot
            
        except Exception as e:
            logger.error(f"Error creating snapshot for {entity_id}: {e}")
            db.rollback()
            return None
    
    @staticmethod
    def get_latest_snapshot(db: Session, entity_id: str) -> Optional[Snapshot]:
        """Get the most recent snapshot for an entity"""
        return db.query(Snapshot).filter(
            Snapshot.entity_id == entity_id
        ).order_by(Snapshot.snapshot_number.desc()).first()
    
    @staticmethod
    def reconstruct_with_snapshot(db: Session, entity_id: str) -> Dict[str, Any]:
        """Reconstruct state using snapshot + incremental events"""
        # Get latest snapshot
        snapshot = SnapshotManager.get_latest_snapshot(db, entity_id)
        
        if not snapshot:
            # No snapshot, reconstruct from all events
            events = db.query(Event).filter(
                Event.entity_id == entity_id
            ).order_by(Event.created_at.asc()).all()
            return StateReconstructor.reconstruct(events)
        
        # Start with snapshot state
        state = dict(snapshot.state_data)
        
        # Get events after snapshot
        events_after = db.query(Event).filter(
            Event.entity_id == entity_id,
            Event.id > snapshot.last_event_id
        ).order_by(Event.created_at.asc()).all()
        
        # Apply incremental events
        for event in events_after:
            StateReconstructor._apply_event(state, event)
        
        logger.info(f"Reconstructed {entity_id} from snapshot #{snapshot.snapshot_number} + {len(events_after)} events")
        return state
    
    @staticmethod
    def cleanup_old_snapshots(db: Session, entity_id: str, keep_count: int = 5):
        """Keep only N most recent snapshots"""
        snapshots = db.query(Snapshot).filter(
            Snapshot.entity_id == entity_id
        ).order_by(Snapshot.snapshot_number.desc()).all()
        
        if len(snapshots) > keep_count:
            to_delete = snapshots[keep_count:]
            for snapshot in to_delete:
                db.delete(snapshot)
            db.commit()
            logger.info(f"Deleted {len(to_delete)} old snapshots for {entity_id}")
