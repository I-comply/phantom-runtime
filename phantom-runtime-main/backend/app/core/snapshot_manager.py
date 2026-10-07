from sqlalchemy.orm import Session
from app.core.models import Event
from app.core.models_v2 import Snapshot
from app.core.event_store import EventStore
from app.core.reconstructor_v2 import StateReconstructorV2
import copy
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
            # Wait for in-flight writers of this entity and block new ones until we commit, so the
            # head we snapshot is final (see EventStore.lock_entity).
            EventStore.lock_entity(db, entity_id)
            # Get all events for reconstruction, in id order (the same order and boundary
            # reconstruct_with_snapshot uses via last_event_id)
            events = db.query(Event).filter(
                Event.entity_id == entity_id
            ).order_by(Event.id.asc()).all()
            
            if not events:
                logger.warning(f"No events found for entity {entity_id}")
                return None
            
            # Reconstruct full state
            state = StateReconstructorV2.reconstruct(events)
            
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
    def get_latest_snapshot(db: Session, entity_id: str, workspace_id: Optional[str] = None) -> Optional[Snapshot]:
        """Get the most recent snapshot for an entity. workspace_id=None means
        unscoped (admin/internal callers only); route handlers must pass the
        caller's own workspace_id for non-admin keys. A snapshot created before
        workspaces existed (workspace_id NULL) is only visible unscoped."""
        q = db.query(Snapshot).filter(Snapshot.entity_id == entity_id)
        if workspace_id is not None:
            q = q.filter(Snapshot.workspace_id == workspace_id)
        return q.order_by(Snapshot.snapshot_number.desc()).first()
    
    @staticmethod
    def reconstruct_with_snapshot(db: Session, entity_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        """Reconstruct state using snapshot + incremental events"""
        # Get latest snapshot
        snapshot = SnapshotManager.get_latest_snapshot(db, entity_id, workspace_id)
        
        if not snapshot:
            # No snapshot, reconstruct from all events
            events = db.query(Event).filter(
                Event.entity_id == entity_id
            ).order_by(Event.id.asc()).all()
            return StateReconstructorV2.reconstruct(events)
        
        # Start with a deep copy of the snapshot state: apply_event mutates nested values
        # (balances, event_history) and must not write through into the loaded snapshot row.
        state = copy.deepcopy(snapshot.state_data)
        
        # Get events after snapshot (same id order and boundary as create_snapshot)
        events_after = db.query(Event).filter(
            Event.entity_id == entity_id,
            Event.id > snapshot.last_event_id
        ).order_by(Event.id.asc()).all()
        
        # Apply incremental events
        for event in events_after:
            StateReconstructorV2.apply_event(state, event)
        
        logger.info(f"Reconstructed {entity_id} from snapshot #{snapshot.snapshot_number} + {len(events_after)} events")
        return state
    
    @staticmethod
    def cleanup_old_snapshots(db: Session, entity_id: str, keep_count: int = 5, workspace_id: Optional[str] = None):
        """Keep only N most recent snapshots. workspace_id=None means unscoped
        (admin/internal callers only) — a non-admin caller must only ever be able
        to delete snapshots belonging to their own workspace."""
        q = db.query(Snapshot).filter(Snapshot.entity_id == entity_id)
        if workspace_id is not None:
            q = q.filter(Snapshot.workspace_id == workspace_id)
        snapshots = q.order_by(Snapshot.snapshot_number.desc()).all()
        
        if len(snapshots) > keep_count:
            to_delete = snapshots[keep_count:]
            for snapshot in to_delete:
                db.delete(snapshot)
            db.commit()
            logger.info(f"Deleted {len(to_delete)} old snapshots for {entity_id}")

    @staticmethod
    def rebuild_snapshots(db: Session, entity_id: Optional[str] = None) -> int:
        """Recompute every snapshot's state_data from the event log with the current reconstructor.

        Snapshots written before the reconstructors were unified were built by the old v1 code and can
        differ from a full replay. Idempotent: returns the number of snapshots whose stored state
        changed (0 when everything already matches). Safe to run online; rows are updated in place.
        Pass entity_id to limit it to one entity."""
        q = db.query(Snapshot)
        if entity_id is not None:
            q = q.filter(Snapshot.entity_id == entity_id)
        changed = 0
        for snapshot in q.order_by(Snapshot.id.asc()).all():
            events = db.query(Event).filter(
                Event.entity_id == snapshot.entity_id,
                Event.id <= snapshot.last_event_id,
            ).order_by(Event.id.asc()).all()
            state = StateReconstructorV2.reconstruct(events)
            if state != snapshot.state_data or snapshot.event_count != len(events):
                snapshot.state_data = state
                snapshot.event_count = len(events)
                changed += 1
        db.commit()
        return changed
