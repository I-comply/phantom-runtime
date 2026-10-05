from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any
from app.core.database import get_db
from app.core.event_store import EventStore
from app.core.deps import require_permission, is_admin
from app.core.models_v3 import APIKey
from datetime import datetime

router = APIRouter(prefix="/api/events", tags=["events"])

# The v1 Event model (app/core/models.py) has no tenant_id column of its own —
# tenant scoping here goes through the EntityWorkspace mapping table instead
# (see event_store.py's module docstring). create_event links entity_id to the
# caller's own workspace the first time it's written; reads are scoped to that
# same link unless the caller holds an admin key.

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
    api_key_obj: APIKey = Depends(require_permission("events", "write")),
):
    """Append a new event to the store. Links entity_id to the caller's own
    workspace (first writer wins — see EventStore.append_event)."""
    stored_event = EventStore.append_event(
        db=db,
        entity_id=event.entity_id,
        event_type=event.event_type,
        payload=event.payload,
        workspace_id=str(api_key_obj.tenant_id),
    )
    return stored_event

@router.get("/entity/{entity_id}", response_model=list[EventResponse])
def get_entity_events(
    entity_id: str,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("events", "read")),
):
    """Get all events for a specific entity. 404s (not an empty list) if the
    caller's workspace has no link to this entity, so "no access" is never
    indistinguishable from "entity exists but has no events"."""
    if not is_admin(api_key_obj, db) and not EventStore.entity_in_workspace(
        db, entity_id, str(api_key_obj.tenant_id)
    ):
        raise HTTPException(status_code=404, detail="entity not found")
    events = EventStore.get_events(db=db, entity_id=entity_id)
    return events

@router.get("/", response_model=list[EventResponse])
def get_all_events(
    limit: int = 100,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("events", "read")),
):
    """Get recent events across all entities in the caller's workspace
    (unscoped — all workspaces — for admin keys)."""
    workspace_id = None if is_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    events = EventStore.get_all_events(db=db, limit=limit, workspace_id=workspace_id)
    return events
