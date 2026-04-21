from typing import Dict, Any, List
from app.core.models import Event

class StateReconstructor:
    @staticmethod
    def reconstruct(events: List[Event]) -> Dict[str, Any]:
        """Reconstruct entity state from event history"""
        state = {}
        
        for event in events:
            event_type = event.event_type
            payload = event.payload
            
            if event_type == "init":
                # Initialize state with payload
                state.update(payload)
            
            elif event_type == "update":
                # Merge updates into state
                state.update(payload)
            
            elif event_type == "delete_field":
                # Remove specific fields
                field = payload.get("field")
                if field and field in state:
                    del state[field]
            
            elif event_type == "compute":
                # Add computed results to state
                state.update(payload)
            
            elif event_type == "reset":
                # Clear state
                state = {}
            
            else:
                # Generic event - merge payload
                state.update(payload)
        
        return state
    
    @staticmethod
    def get_event_count(events: List[Event]) -> int:
        """Get total event count"""
        return len(events)
