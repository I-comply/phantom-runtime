from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any
from app.core.database import get_db
from app.core.event_store import EventStore
from app.core.deps import require_permission
from datetime import datetime

router = APIRouter(prefix="/api/events", tags=["events"])

# NOTE: the v1 Event model (app/core/models.py) has no tenant_id column, so unlike
# the v3 event routes these endpoints can require a valid API key but cannot filter
# results by tenant — any caller with events:read can see every v1 event, regardless
# of which workspace/tenant it is "for". Closing that needs a schema migration
# (add + backfill a tenant_id column), not something to fake here. Prefer the v3
# event endpoints (/api/v3/events/*) for anything that needs real tenant isolation.

class EventCreate(BaseModel):
    entity_id: str
    event_type: str
    payload: Dict[str, Any]

class EventResponse(BaseModel):
    id: int
    entity_id: str
    event_type: str
    payload: Dict[str, Any]
    created_at: datetime
    
    class Config:
        from_attributes = True

@router.post("/", response_model=EventResponse)
def create_event(
    event: EventCreate,
    db: Session = Depends(get_db),
    _auth=Depends(require_permission("events", "write")),
):
    """Append a new event to the store"""
    stored_event = EventStore.append_event(
        db=db,
        entity_id=event.entity_id,
        event_type=event.event_type,
        payload=event.payload
    )
    return stored_event

@router.get("/entity/{entity_id}", response_model=list[EventResponse])
def get_entity_events(
    entity_id: str,
    db: Session = Depends(get_db),
    _auth=Depends(require_permission("events", "read")),
):
    """Get all events for a specific entity"""
    events = EventStore.get_events(db=db, entity_id=entity_id)
    return events

@router.get("/", response_model=list[EventResponse])
def get_all_events(
    limit: int = 100,
    db: Session = Depends(get_db),
    _auth=Depends(require_permission("events", "read")),
):
    """Get recent events across all entities"""
    events = EventStore.get_all_events(db=db, limit=limit)
    return events
