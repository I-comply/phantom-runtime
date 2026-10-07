from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any
from app.core.database import get_db
from app.core.defi_manager import DeFiEventManager, AsyncPipeline
from app.core.deps import require_permission, is_platform_admin
from app.core.models_v3 import APIKey
from datetime import datetime

router = APIRouter(prefix="/api/defi", tags=["defi"])

class DeFiEventCreate(BaseModel):
    entity_id: str
    event_type: str
    asset: str
    amount: str
    price: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}

class DeFiEventResponse(BaseModel):
    id: int
    entity_id: str
    event_type: str
    asset: str
    amount: str
    price: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

@router.post("/events", response_model=DeFiEventResponse)
def create_defi_event(
    event: DeFiEventCreate,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("defi", "write")),
):
    """Create a DeFi event (deposit, withdraw, trade, etc.), stamped with the
    caller's own workspace (never caller-supplied)."""
    try:
        defi_event = DeFiEventManager.create_defi_event(
            db=db,
            entity_id=event.entity_id,
            event_type=event.event_type,
            asset=event.asset,
            amount=event.amount,
            price=event.price,
            metadata=event.metadata,
            workspace_id=str(api_key_obj.tenant_id),
        )
        return defi_event
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/portfolio/{entity_id}")
def get_portfolio(
    entity_id: str,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("defi", "read")),
):
    """Get portfolio summary for an entity, scoped to the caller's own
    workspace (unscoped for admin keys)"""
    workspace_id = None if is_platform_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    portfolio = DeFiEventManager.get_entity_portfolio(db, entity_id, workspace_id)
    return portfolio

@router.get("/supported-events")
def get_supported_events():
    """Get list of supported DeFi event types"""
    return {
        "event_types": DeFiEventManager.SUPPORTED_EVENT_TYPES,
        "note": "Fork-ready DeFi abstraction layer. Not active trading."
    }
