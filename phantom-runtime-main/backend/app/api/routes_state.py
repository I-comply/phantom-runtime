from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, List
from app.core.database import get_db
from app.core.event_store import EventStore
from app.core.snapshot_manager import SnapshotManager
from app.core.reconstructor_v2 import StateReconstructorV2

router = APIRouter(prefix="/api/state", tags=["state"])

class StateResponse(BaseModel):
    entity_id: str
    state: Dict[str, Any]
    event_count: int
    runtime_status: str
    snapshot_used: bool = False
    snapshot_number: int = None

class AgentRunRequest(BaseModel):
    entity_id: str
    operation: str = "process"

class AgentRunResponse(BaseModel):
    entity_id: str
    result: Dict[str, Any]
    status: str

@router.get("/{entity_id}", response_model=StateResponse)
def get_entity_state(entity_id: str, db: Session = Depends(get_db)):
    """Reconstruct entity state using snapshot optimization"""
    events = EventStore.get_events(db=db, entity_id=entity_id)
    
    if not events:
        raise HTTPException(status_code=404, detail="No events found for entity")
    
    # Try snapshot-optimized reconstruction
    snapshot = SnapshotManager.get_latest_snapshot(db, entity_id)
    
    if snapshot:
        state = SnapshotManager.reconstruct_with_snapshot(db, entity_id)
        snapshot_used = True
        snapshot_number = snapshot.snapshot_number
    else:
        state = StateReconstructorV2.reconstruct(events)
        snapshot_used = False
        snapshot_number = None
    
    event_count = len(events)
    
    # Auto-create snapshot if threshold reached
    if SnapshotManager.should_create_snapshot(db, entity_id):
        SnapshotManager.create_snapshot(db, entity_id)
    
    return StateResponse(
        entity_id=entity_id,
        state=state,
        event_count=event_count,
        runtime_status="active",
        snapshot_used=snapshot_used,
        snapshot_number=snapshot_number
    )

@router.get("/", response_model=List[str])
def get_all_entities(db: Session = Depends(get_db)):
    """Get list of all entity IDs"""
    entity_ids = EventStore.get_all_entity_ids(db=db)
    return entity_ids

@router.post("/agent/run", response_model=AgentRunResponse)
def agent_run(request: AgentRunRequest, db: Session = Depends(get_db)):
    """Execute ephemeral agent operation and write result as event"""
    events = EventStore.get_events(db=db, entity_id=request.entity_id)
    
    if not events:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    # Use snapshot-optimized reconstruction
    state = SnapshotManager.reconstruct_with_snapshot(db, request.entity_id)
    
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
        payload=result
    )
    
    return AgentRunResponse(
        entity_id=request.entity_id,
        result=result,
        status="completed"
    )
