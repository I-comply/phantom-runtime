from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, Optional
from app.core.database import get_db
from app.core.snapshot_manager import SnapshotManager
from datetime import datetime

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])

class SnapshotResponse(BaseModel):
    id: int
    entity_id: str
    snapshot_number: int
    event_count: int
    last_event_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class SnapshotCreateRequest(BaseModel):
    entity_id: str
    workspace_id: Optional[str] = None

@router.post("/", response_model=SnapshotResponse)
def create_snapshot(request: SnapshotCreateRequest, db: Session = Depends(get_db)):
    """Manually create a snapshot for an entity"""
    snapshot = SnapshotManager.create_snapshot(
        db=db,
        entity_id=request.entity_id,
        workspace_id=request.workspace_id
    )
    
    if not snapshot:
        raise HTTPException(status_code=400, detail="Failed to create snapshot")
    
    return snapshot

@router.get("/entity/{entity_id}/latest", response_model=SnapshotResponse)
def get_latest_snapshot(entity_id: str, db: Session = Depends(get_db)):
    """Get latest snapshot for an entity"""
    snapshot = SnapshotManager.get_latest_snapshot(db, entity_id)
    
    if not snapshot:
        raise HTTPException(status_code=404, detail="No snapshot found")
    
    return snapshot

@router.get("/entity/{entity_id}/state")
def get_state_with_snapshot(entity_id: str, db: Session = Depends(get_db)):
    """Get reconstructed state using snapshot optimization"""
    try:
        state = SnapshotManager.reconstruct_with_snapshot(db, entity_id)
        snapshot = SnapshotManager.get_latest_snapshot(db, entity_id)
        
        return {
            "entity_id": entity_id,
            "state": state,
            "snapshot_used": snapshot.snapshot_number if snapshot else None,
            "reconstruction_method": "snapshot" if snapshot else "full_replay"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/entity/{entity_id}/cleanup")
def cleanup_old_snapshots(entity_id: str, keep_count: int = 5, db: Session = Depends(get_db)):
    """Clean up old snapshots, keeping only N most recent"""
    SnapshotManager.cleanup_old_snapshots(db, entity_id, keep_count)
    return {"status": "cleaned", "entity_id": entity_id, "kept": keep_count}
