import copy
from typing import Dict, Any, List
from app.core.models import Event

class StateReconstructorV2:
    """The one state reconstructor. Every read path (full replay, snapshot creation, snapshot +
    incremental replay) goes through apply_event, so they cannot disagree.

    Replay is a pure function of the ordered events: apply_event never writes through into an
    event's payload, and the returned state never aliases it (payloads are deep-copied in)."""
    
    @staticmethod
    def reconstruct(events: List[Event]) -> Dict[str, Any]:
        """Reconstruct entity state from event history (events must be in id order)"""
        state = {}
        for event in events:
            StateReconstructorV2.apply_event(state, event)
        return state
    
    @staticmethod
    def apply_event(state: Dict[str, Any], event: Event) -> None:
        """Apply a single event to state (in-place mutation of `state` only)"""
        event_type = event.event_type
        payload = copy.deepcopy(event.payload)
        
        if event_type == "init":
            state.update(payload)
        
        elif event_type == "update":
            state.update(payload)
        
        elif event_type == "delete_field":
            field = payload.get("field")
            if field and field in state:
                del state[field]
        
        elif event_type == "compute":
            state.update(payload)
        
        elif event_type == "reset":
            state.clear()
        
        # DeFi event types
        elif event_type in ["deposit", "withdraw", "trade", "transfer", "stake", "unstake"]:
            # Apply financial event logic
            StateReconstructorV2._apply_defi_event(state, event_type, payload)
        
        else:
            # Generic event - merge payload
            state.update(payload)
    
    # Backward-compatible name (snapshot_manager and older callers used the underscore form).
    _apply_event = apply_event

    @staticmethod
    def _apply_defi_event(state: Dict[str, Any], event_type: str, payload: Dict[str, Any]) -> None:
        """Apply DeFi-specific event logic"""
        # Initialize balances if not present
        if "balances" not in state:
            state["balances"] = {}
        
        asset = payload.get("asset", "USD")
        amount = float(payload.get("amount", 0))
        
        if event_type == "deposit":
            state["balances"][asset] = state["balances"].get(asset, 0) + amount
        
        elif event_type == "withdraw":
            state["balances"][asset] = state["balances"].get(asset, 0) - amount
        
        elif event_type == "trade":
            from_asset = payload.get("from_asset")
            to_asset = payload.get("to_asset")
            from_amount = float(payload.get("from_amount", 0))
            to_amount = float(payload.get("to_amount", 0))
            
            if from_asset:
                state["balances"][from_asset] = state["balances"].get(from_asset, 0) - from_amount
            if to_asset:
                state["balances"][to_asset] = state["balances"].get(to_asset, 0) + to_amount
        
        elif event_type == "transfer":
            # Transfer out
            state["balances"][asset] = state["balances"].get(asset, 0) - amount
        
        # Store event metadata
        if "event_history" not in state:
            state["event_history"] = []
        state["event_history"].append({
            "type": event_type,
            "asset": asset,
            "amount": amount,
            **payload
        })
    
    @staticmethod
    def get_event_count(events: List[Event]) -> int:
        return len(events)
