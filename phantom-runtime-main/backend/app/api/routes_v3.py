from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from app.core.database import get_db
from app.core.event_engine_v3 import EventEngineV3, AsyncEventPipeline
from app.core.strategy_engine import StrategyEngine
from app.core.security import SecurityManager, RBACMiddleware
from app.core.deps import require_permission, require_api_key, is_admin
from app.core.config import settings
from app.core.models_v3 import APIKey
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
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("events", "write")),
):
    """Create event with hash chaining. Requires an API key with events:write;
    the event is stamped with the caller's own tenant_id (not caller-supplied)."""
    created_event = EventEngineV3.create_event(
        db=db,
        entity_id=event.entity_id,
        event_type=event.event_type,
        payload=event.payload,
        tenant_id=str(api_key_obj.tenant_id),
        priority=event.priority,
        source=event.source,
        created_by=api_key_obj.name
    )

    return {
        "id": created_event.id,
        "entity_id": created_event.entity_id,
        "event_hash": created_event.event_hash,
        "block_index": created_event.block_index,
        "created_at": created_event.created_at
    }

@router.get("/events/chain/{entity_id}")
def get_event_chain(
    entity_id: str,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("events", "read")),
):
    """Get complete event chain for entity. Scoped to the caller's own tenant
    unless the caller is an admin key (admins see across tenants)."""
    tenant_id = None if is_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    events = EventEngineV3.get_entity_chain(db, entity_id, tenant_id)
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
def verify_chain_integrity(
    entity_id: str,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("events", "read")),
):
    """Verify hash chain integrity. Same tenant scoping as /events/chain."""
    tenant_id = None if is_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    is_valid = EventEngineV3.verify_chain_integrity(db, entity_id, tenant_id)
    return {
        "entity_id": entity_id,
        "chain_valid": is_valid
    }

# === Async Pipeline ===

@router.post("/events/queue")
def queue_event(
    event: EventCreateV3,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("events", "write")),
):
    """Add event to async queue (the event will belong to the caller's workspace)"""
    queue_item = AsyncEventPipeline.queue_event(
        db=db,
        entity_id=event.entity_id,
        event_data={
            "event_type": event.event_type,
            "payload": event.payload,
            "source": event.source
        },
        priority=event.priority,
        tenant_id=str(api_key_obj.tenant_id)
    )
    return {
        "queue_id": str(queue_item.id),
        "status": queue_item.status
    }

@router.post("/events/process-queue")
def process_queue(
    batch_size: int = 100,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("events", "write")),
):
    """Process queued events (manual trigger). A non-admin key processes only its own workspace's
    items; admin keys process every tenant's (including legacy items queued without a tenant)."""
    batch_size = max(1, min(batch_size, 1000))
    count = AsyncEventPipeline.process_queue_batch(
        db, batch_size, tenant_id=None if is_admin(api_key_obj, db) else str(api_key_obj.tenant_id))
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
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("strategies", "write")),
):
    """Create new strategy. Requires an API key with strategies:write.
    `code` is later exec()'d (see StrategyEngine._execute_code) — treat
    strategies:write as granting arbitrary code execution, not a data-write."""

    created_strategy = StrategyEngine.create_strategy(
        db=db,
        name=strategy.name,
        strategy_type=strategy.strategy_type,
        code=strategy.code,
        config=strategy.config,
        tenant_id=str(api_key_obj.tenant_id)
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
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("strategies", "execute")),
):
    """Execute strategy on entity. Requires an API key with strategies:execute. A non-admin key can
    only run its own workspace's strategies, over its own workspace's events (404 otherwise)."""
    try:
        execution = StrategyEngine.execute_strategy(
            db=db,
            strategy_id=strategy_id,
            entity_id=entity_id,
            emit_events=emit_events,
            tenant_id=None if is_admin(api_key_obj, db) else str(api_key_obj.tenant_id),
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="strategy not found")
    
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
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_bootstrap_key: Optional[str] = Header(None, alias="X-Bootstrap-Key"),
):
    """Create new API key.

    Gated by EITHER an existing API key with api_keys:write, OR the one-time
    PHANTOM_BOOTSTRAP_ADMIN_KEY env var (for minting the very first admin key
    on a fresh deployment, when no API key exists yet to authenticate with).
    Unset PHANTOM_BOOTSTRAP_ADMIN_KEY once you have a real admin key."""
    import hmac as _hmac

    authorized = False
    if x_bootstrap_key and settings.BOOTSTRAP_ADMIN_KEY:
        authorized = _hmac.compare_digest(x_bootstrap_key, settings.BOOTSTRAP_ADMIN_KEY)
    if not authorized and x_api_key:
        api_key_obj = SecurityManager.verify_api_key(db, x_api_key)
        if api_key_obj and RBACMiddleware.check_permission(api_key_obj, db, "api_keys", "write"):
            authorized = True
    if not authorized:
        raise HTTPException(status_code=401, detail="requires an API key with api_keys:write, or X-Bootstrap-Key")

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
def list_roles(
    db: Session = Depends(get_db),
    _auth: APIKey = Depends(require_permission("api_keys", "read")),
):
    """List available RBAC roles (admin keys only: this exposes the permission model)"""
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
