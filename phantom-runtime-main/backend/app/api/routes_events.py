from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any
from app.core.database import get_db
from app.core.event_store import EventStore
from datetime import datetime

router = APIRouter(prefix="/api/events", tags=["events"])

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
def create_event(event: EventCreate, db: Session = Depends(get_db)):
    """Append a new event to the store"""
    stored_event = EventStore.append_event(
        db=db,
        entity_id=event.entity_id,
        event_type=event.event_type,
        payload=event.payload
    )
    return stored_event

@router.get("/entity/{entity_id}", response_model=list[EventResponse])
def get_entity_events(entity_id: str, db: Session = Depends(get_db)):
    """Get all events for a specific entity"""
    events = EventStore.get_events(db=db, entity_id=entity_id)
    return events

@router.get("/", response_model=list[EventResponse])
def get_all_events(limit: int = 100, db: Session = Depends(get_db)):
    """Get recent events across all entities"""
    events = EventStore.get_all_events(db=db, limit=limit)
    return events
