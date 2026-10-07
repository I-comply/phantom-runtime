from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from app.core.database import get_db
from app.core.event_store import EventStore
from app.core.snapshot_manager import SnapshotManager
from app.core.reconstructor_v2 import StateReconstructorV2
from app.core.deps import require_permission, is_platform_admin
from app.core.models_v3 import APIKey

router = APIRouter(prefix="/api/state", tags=["state"])

class StateResponse(BaseModel):
    entity_id: str
    state: Dict[str, Any]
    event_count: int
    runtime_status: str
    snapshot_used: bool = False
    snapshot_number: Optional[int] = None

class AgentRunRequest(BaseModel):
    entity_id: str
    operation: str = "process"

class AgentRunResponse(BaseModel):
    entity_id: str
    result: Dict[str, Any]
    status: str

def _check_access(api_key_obj: APIKey, db: Session, entity_id: str):
    """404s (not a silent empty result) when the caller's workspace has no link
    to this entity — see EventStore's module docstring for why v1 entities are
    scoped through EntityWorkspace rather than a tenant_id column."""
    if not is_platform_admin(api_key_obj, db) and not EventStore.entity_in_workspace(
        db, entity_id, str(api_key_obj.tenant_id)
    ):
        raise HTTPException(status_code=404, detail="entity not found")

@router.get("/{entity_id}", response_model=StateResponse)
def get_entity_state(
    entity_id: str,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("events", "read")),
):
    """Reconstruct entity state using snapshot optimization"""
    _check_access(api_key_obj, db, entity_id)
    events = EventStore.get_events(db=db, entity_id=entity_id)

    if not events:
        raise HTTPException(status_code=404, detail="No events found for entity")

    # Try snapshot-optimized reconstruction
    workspace_id = None if is_platform_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    snapshot = SnapshotManager.get_latest_snapshot(db, entity_id, workspace_id)

    if snapshot:
        state = SnapshotManager.reconstruct_with_snapshot(db, entity_id, workspace_id)
        snapshot_used = True
        snapshot_number = snapshot.snapshot_number
    else:
        state = StateReconstructorV2.reconstruct(events)
        snapshot_used = False
        snapshot_number = None

    event_count = len(events)

    # Auto-create snapshot if threshold reached
    if SnapshotManager.should_create_snapshot(db, entity_id):
        SnapshotManager.create_snapshot(db, entity_id, workspace_id=str(api_key_obj.tenant_id))

    return StateResponse(
        entity_id=entity_id,
        state=state,
        event_count=event_count,
        runtime_status="active",
        snapshot_used=snapshot_used,
        snapshot_number=snapshot_number
    )

@router.get("/", response_model=List[str])
def get_all_entities(
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("events", "read")),
):
    """Get list of entity IDs in the caller's workspace (unscoped for admin keys)"""
    workspace_id = None if is_platform_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    entity_ids = EventStore.get_all_entity_ids(db=db, workspace_id=workspace_id)
    return entity_ids

@router.post("/agent/run", response_model=AgentRunResponse)
def agent_run(
    request: AgentRunRequest,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("events", "write")),
):
    """Execute ephemeral agent operation and write result as event"""
    _check_access(api_key_obj, db, request.entity_id)
    events = EventStore.get_events(db=db, entity_id=request.entity_id)

    if not events:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Use snapshot-optimized reconstruction
    workspace_id = None if is_platform_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    state = SnapshotManager.reconstruct_with_snapshot(db, request.entity_id, workspace_id)

    # Perform ephemeral computation
    result = {
        "operation": request.operation,
        "processed_state_size": len(str(state)),
        "field_count": len(state),
        "status": "completed"
    }

    # Write result as new event
    EventStore.append_event(
        db=db,
        entity_id=request.entity_id,
        event_type="compute",
        payload=result,
        workspace_id=str(api_key_obj.tenant_id),
    )

    return AgentRunResponse(
        entity_id=request.entity_id,
        result=result,
        status="completed"
    )
