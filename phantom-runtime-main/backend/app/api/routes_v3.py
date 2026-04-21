from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from app.core.database import get_db
from app.core.event_engine_v3 import EventEngineV3, AsyncEventPipeline
from app.core.strategy_engine import StrategyEngine
from app.core.security import SecurityManager, RBACMiddleware
from datetime import datetime

router = APIRouter(prefix="/api/v3", tags=["v3"])

# === Event Management ===

class EventCreateV3(BaseModel):
    entity_id: str
    event_type: str
    payload: Dict[str, Any]
    priority: str = 'normal'
    source: str = 'api'

@router.post("/events")
def create_event_v3(
    event: EventCreateV3,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db)
):
    """Create event with hash chaining"""
    
    tenant_id = None
    created_by = None
    
    # Verify API key if provided
    if x_api_key:
        api_key_obj = SecurityManager.verify_api_key(db, x_api_key)
        if api_key_obj:
            RBACMiddleware.require_permission(api_key_obj, db, 'events', 'write')
            tenant_id = str(api_key_obj.tenant_id)
            created_by = api_key_obj.name
    
    created_event = EventEngineV3.create_event(
        db=db,
        entity_id=event.entity_id,
        event_type=event.event_type,
        payload=event.payload,
        tenant_id=tenant_id,
        priority=event.priority,
        source=event.source,
        created_by=created_by
    )
    
    return {
        "id": created_event.id,
        "entity_id": created_event.entity_id,
        "event_hash": created_event.event_hash,
        "block_index": created_event.block_index,
        "created_at": created_event.created_at
    }

@router.get("/events/chain/{entity_id}")
def get_event_chain(entity_id: str, db: Session = Depends(get_db)):
    """Get complete event chain for entity"""
    events = EventEngineV3.get_entity_chain(db, entity_id)
    return {
        "entity_id": entity_id,
        "chain_length": len(events),
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "event_hash": e.event_hash,
                "block_index": e.block_index,
                "payload": e.payload,
                "created_at": e.created_at
            }
            for e in events
        ]
    }

@router.get("/events/verify/{entity_id}")
def verify_chain_integrity(entity_id: str, db: Session = Depends(get_db)):
    """Verify hash chain integrity"""
    is_valid = EventEngineV3.verify_chain_integrity(db, entity_id)
    return {
        "entity_id": entity_id,
        "chain_valid": is_valid
    }

# === Async Pipeline ===

@router.post("/events/queue")
def queue_event(
    event: EventCreateV3,
    db: Session = Depends(get_db)
):
    """Add event to async queue"""
    queue_item = AsyncEventPipeline.queue_event(
        db=db,
        entity_id=event.entity_id,
        event_data={
            "event_type": event.event_type,
            "payload": event.payload,
            "source": event.source
        },
        priority=event.priority
    )
    return {
        "queue_id": str(queue_item.id),
        "status": queue_item.status
    }

@router.post("/events/process-queue")
def process_queue(batch_size: int = 100, db: Session = Depends(get_db)):
    """Process queued events (manual trigger)"""
    count = AsyncEventPipeline.process_queue_batch(db, batch_size)
    return {
        "processed_count": count
    }

# === Strategy Management ===

class StrategyCreate(BaseModel):
    name: str
    strategy_type: str
    code: Optional[str] = None
    config: Optional[Dict[str, Any]] = {}

@router.post("/strategies")
def create_strategy(
    strategy: StrategyCreate,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db)
):
    """Create new strategy"""
    
    tenant_id = None
    if x_api_key:
        api_key_obj = SecurityManager.verify_api_key(db, x_api_key)
        if api_key_obj:
            RBACMiddleware.require_permission(api_key_obj, db, 'strategies', 'write')
            tenant_id = str(api_key_obj.tenant_id)
    
    created_strategy = StrategyEngine.create_strategy(
        db=db,
        name=strategy.name,
        strategy_type=strategy.strategy_type,
        code=strategy.code,
        config=strategy.config,
        tenant_id=tenant_id
    )
    
    return {
        "id": str(created_strategy.id),
        "name": created_strategy.name,
        "strategy_type": created_strategy.strategy_type
    }

@router.post("/strategies/{strategy_id}/execute")
def execute_strategy(
    strategy_id: str,
    entity_id: str,
    emit_events: bool = True,
    db: Session = Depends(get_db)
):
    """Execute strategy on entity"""
    execution = StrategyEngine.execute_strategy(
        db=db,
        strategy_id=strategy_id,
        entity_id=entity_id,
        emit_events=emit_events
    )
    
    return {
        "execution_id": str(execution.id),
        "status": execution.status,
        "result": execution.result,
        "output_events": execution.output_events
    }

@router.get("/strategies/builtins")
def list_builtin_strategies():
    """List available built-in strategies"""
    return {
        "strategies": list(StrategyEngine.BUILTIN_STRATEGIES.keys()),
        "templates": {
            name: {"description": code.split('\n')[0].replace('# ', '')}
            for name, code in StrategyEngine.BUILTIN_STRATEGIES.items()
        }
    }

# === Security & RBAC ===

class APIKeyCreate(BaseModel):
    tenant_id: str
    role: str
    name: str

@router.post("/security/api-keys")
def create_api_key(
    request: APIKeyCreate,
    db: Session = Depends(get_db)
):
    """Create new API key"""
    api_key, plaintext_key = SecurityManager.create_api_key(
        db=db,
        tenant_id=request.tenant_id,
        role_name=request.role,
        name=request.name
    )
    
    return {
        "id": str(api_key.id),
        "key": plaintext_key,  # Only returned once!
        "role": request.role,
        "warning": "Store this key securely - it will not be shown again"
    }

@router.get("/security/roles")
def list_roles(db: Session = Depends(get_db)):
    """List available RBAC roles"""
    from app.core.models_v3 import Role
    roles = db.query(Role).all()
    return {
        "roles": [
            {
                "name": r.name,
                "permissions": r.permissions
            }
            for r in roles
        ]
    }

# === System Info ===

@router.get("/system/info")
def system_info_v3():
    return {
        "platform": "Phantom Finance",
        "version": "3.0.0",
        "codename": "DARK_OPERATOR",
        "features": {
            "event_chaining": "SHA256 hash chains for audit trail",
            "async_pipeline": "Queue-based ingestion with burst support",
            "strategy_engine": "Sandboxed plugin execution",
            "rbac": "Role-based access control (admin, agent, viewer, system)",
            "hmac_signing": "Event integrity verification",
            "defi_ready": "Financial event abstractions (fork-ready)"
        },
        "performance_targets": {
            "events_per_sec": "10k-25k (async mode)",
            "reconstruction_latency": "<100ms with snapshots",
            "scalability": "1M+ entities"
        }
    }
