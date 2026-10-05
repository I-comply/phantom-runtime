from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, Optional
from app.core.database import get_db
from app.core.snapshot_manager import SnapshotManager
from app.core.event_store import EventStore
from app.core.deps import require_permission, is_admin
from app.core.models_v3 import APIKey
from datetime import datetime

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])

def _check_access(api_key_obj: APIKey, db: Session, entity_id: str):
    """404s when the caller's workspace has no link to this entity. Needed even
    for snapshot-scoped reads: reconstruct_with_snapshot's full-replay fallback
    (no snapshot yet) reads the v1 Event table directly, which has no tenant
    column of its own — scoping only the snapshot lookup isn't enough to stop
    that fallback from replaying another tenant's event history."""
    if not is_admin(api_key_obj, db) and not EventStore.entity_in_workspace(
        db, entity_id, str(api_key_obj.tenant_id)
    ):
        raise HTTPException(status_code=404, detail="entity not found")

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

@router.post("/", response_model=SnapshotResponse)
def create_snapshot(
    request: SnapshotCreateRequest,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("snapshots", "write")),
):
    """Manually create a snapshot for an entity, stamped with the caller's own
    workspace (never caller-supplied — a client can no longer claim a snapshot
    belongs to a workspace it doesn't hold a key for)."""
    snapshot = SnapshotManager.create_snapshot(
        db=db,
        entity_id=request.entity_id,
        workspace_id=str(api_key_obj.tenant_id),
    )

    if not snapshot:
        raise HTTPException(status_code=400, detail="Failed to create snapshot")

    return snapshot

@router.get("/entity/{entity_id}/latest", response_model=SnapshotResponse)
def get_latest_snapshot(
    entity_id: str,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("snapshots", "read")),
):
    """Get latest snapshot for an entity, scoped to the caller's own workspace
    (unscoped for admin keys)"""
    _check_access(api_key_obj, db, entity_id)
    workspace_id = None if is_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    snapshot = SnapshotManager.get_latest_snapshot(db, entity_id, workspace_id)

    if not snapshot:
        raise HTTPException(status_code=404, detail="No snapshot found")

    return snapshot

@router.get("/entity/{entity_id}/state")
def get_state_with_snapshot(
    entity_id: str,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("snapshots", "read")),
):
    """Get reconstructed state using snapshot optimization, scoped to the
    caller's own workspace (unscoped for admin keys)"""
    _check_access(api_key_obj, db, entity_id)
    workspace_id = None if is_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    try:
        state = SnapshotManager.reconstruct_with_snapshot(db, entity_id, workspace_id)
        snapshot = SnapshotManager.get_latest_snapshot(db, entity_id, workspace_id)

        return {
            "entity_id": entity_id,
            "state": state,
            "snapshot_used": snapshot.snapshot_number if snapshot else None,
            "reconstruction_method": "snapshot" if snapshot else "full_replay"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/entity/{entity_id}/cleanup")
def cleanup_old_snapshots(
    entity_id: str,
    keep_count: int = 5,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("snapshots", "write")),
):
    """Clean up old snapshots, keeping only N most recent. A non-admin caller
    can only ever delete snapshots belonging to its own workspace."""
    _check_access(api_key_obj, db, entity_id)
    workspace_id = None if is_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    SnapshotManager.cleanup_old_snapshots(db, entity_id, keep_count, workspace_id)
    return {"status": "cleaned", "entity_id": entity_id, "kept": keep_count}
