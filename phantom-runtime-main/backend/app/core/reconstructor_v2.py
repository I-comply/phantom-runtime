import copy
from typing import Dict, Any, List
from app.core.models import Event
from app.core import money

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
        elif event_type in ["deposit", "withdraw", "trade", "transfer", "stake", "unstake", "claim_rewards"]:
            # Apply financial event logic
            StateReconstructorV2._apply_defi_event(state, event_type, payload)
        
        else:
            # Generic event - merge payload
            state.update(payload)
    
    # Backward-compatible name (snapshot_manager and older callers used the underscore form).
    _apply_event = apply_event

    @staticmethod
    def _apply_defi_event(state: Dict[str, Any], event_type: str, payload: Dict[str, Any]) -> None:
        """Apply DeFi-specific event logic with exact decimal arithmetic.

        Balances are canonical decimal strings. Legacy numeric balances (snapshots written before this
        change) are read exactly and rewritten as strings on the next update; unusable amounts count
        as 0 and are flagged in event_history instead of raising, so one bad event can't make an
        entity unreadable."""
        if not isinstance(state.get("balances"), dict):
            state["balances"] = {}
        bal = state["balances"]

        asset = payload.get("asset", "USD")
        amount = money.lenient(payload.get("amount", 0))

        if event_type in ("deposit", "claim_rewards"):
            bal[asset] = money.fmt(money.add(money.lenient(bal.get(asset, 0)), amount))

        elif event_type in ("withdraw", "transfer"):  # transfer: the out leg
            bal[asset] = money.fmt(money.sub(money.lenient(bal.get(asset, 0)), amount))

        elif event_type == "trade":
            from_asset = payload.get("from_asset")
            to_asset = payload.get("to_asset")
            from_amount = money.lenient(payload.get("from_amount", 0))
            to_amount = money.lenient(payload.get("to_amount", 0))

            if from_asset:
                bal[from_asset] = money.fmt(money.sub(money.lenient(bal.get(from_asset, 0)), from_amount))
            if to_asset:
                bal[to_asset] = money.fmt(money.add(money.lenient(bal.get(to_asset, 0)), to_amount))

        # Store event metadata. Canonical values win over the raw payload's.
        if "event_history" not in state:
            state["event_history"] = []
        entry = dict(payload)
        entry.update({"type": event_type, "asset": asset, "amount": money.fmt(amount)})
        for k in ("from_amount", "to_amount"):
            if k in payload:
                entry[k] = money.fmt(money.lenient(payload[k]))
        if "amount" in payload and not money.usable(payload["amount"]):
            entry["invalid_amount"] = True
        state["event_history"].append(entry)
    
    @staticmethod
    def get_event_count(events: List[Event]) -> int:
        return len(events)
