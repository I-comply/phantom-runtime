from sqlalchemy.orm import Session
from app.core.models import Event
from datetime import datetime, timezone
from typing import List, Dict, Any

class EventStore:
    @staticmethod
    def append_event(
        db: Session,
        entity_id: str,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Event:
        """Append a new event to the store"""
        event = Event(
            entity_id=entity_id,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(timezone.utc)
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    
    @staticmethod
    def get_events(db: Session, entity_id: str) -> List[Event]:
        """Retrieve all events for an entity in chronological order"""
        return db.query(Event).filter(
            Event.entity_id == entity_id
        ).order_by(Event.created_at.asc()).all()
    
    @staticmethod
    def get_all_events(db: Session, limit: int = 100) -> List[Event]:
        """Retrieve recent events across all entities"""
        return db.query(Event).order_by(
            Event.created_at.desc()
        ).limit(limit).all()
    
    @staticmethod
    def get_all_entity_ids(db: Session) -> List[str]:
        """Get list of all unique entity IDs"""
        result = db.query(Event.entity_id).distinct().all()
        return [row[0] for row in result]
