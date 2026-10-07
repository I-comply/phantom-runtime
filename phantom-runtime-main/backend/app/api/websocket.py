"""WebSocket endpoints. Both require an API key with events:read, sent as the FIRST message
({"type": "auth", "api_key": "..."}) within WS_AUTH_TIMEOUT_S. Browsers can't set headers on a
WebSocket and a key in the URL ends up in logs, so the key travels in the first frame instead.
Everything sent back is scoped to the key's workspace; only a platform admin key (see
app.core.deps.is_platform_admin) sees global figures."""
import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

WS_AUTH_TIMEOUT_S = 5.0
MAX_MESSAGE_CHARS = 4096
MAX_WS_CONNECTIONS = 200
MAX_WS_PER_KEY = 10
REAUTH_S = 60.0              # a revoked or expired key is dropped within this long
METRICS_INTERVAL_S = 2.0
METRICS_CACHE_TTL_S = 5.0    # one COUNT per scope per TTL, however many clients are connected

CLOSE_UNAUTHORIZED = 4401
CLOSE_TOO_MANY = 1013
CLOSE_TOO_BIG = 1009


@dataclass(frozen=True)
class Principal:
    key_id: str
    tenant_id: str
    platform: bool

    def can_see(self, tenant_id: Optional[str]) -> bool:
        return self.platform or (tenant_id is not None and tenant_id == self.tenant_id)


def _verify(raw_key: str) -> Optional[Principal]:
    """Blocking: runs in a worker thread (sync SQLAlchemy must not run on the event loop)."""
    from app.core.database import SessionLocal
    from app.core.deps import is_platform_admin
    from app.core.security import SecurityManager, RBACMiddleware
    db = SessionLocal()
    try:
        key = SecurityManager.verify_api_key(db, raw_key)
        if not key or not RBACMiddleware.check_permission(key, db, "events", "read"):
            return None
        return Principal(str(key.id), str(key.tenant_id), is_platform_admin(key, db))
    finally:
        db.close()


async def _reject(websocket: WebSocket, code: int, error: str):
    try:
        await websocket.send_json({"type": "auth_error" if code == CLOSE_UNAUTHORIZED else "error", "error": error})
        await websocket.close(code=code)
    except Exception:
        pass


async def _authenticate(websocket: WebSocket) -> Optional[Principal]:
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), WS_AUTH_TIMEOUT_S)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await _reject(websocket, CLOSE_UNAUTHORIZED, "auth_required")
        return None
    if len(raw) > MAX_MESSAGE_CHARS:
        await _reject(websocket, CLOSE_UNAUTHORIZED, "auth_required")
        return None
    try:
        msg = json.loads(raw)
        key = msg["api_key"] if isinstance(msg, dict) and msg.get("type") == "auth" else None
    except (ValueError, KeyError):
        key = None
    principal = await asyncio.to_thread(_verify, key) if isinstance(key, str) and key else None
    if principal is None:
        await _reject(websocket, CLOSE_UNAUTHORIZED, "invalid_api_key")
        return None
    return principal


class ConnectionManager:
    def __init__(self):
        self.connections: List[tuple] = []  # (websocket, Principal)
        self.buffers: Dict[str, List[Dict[str, Any]]] = {}  # per tenant
        self.max_buffer_size = 100
        self.loop = None  # the server's event loop, recorded when a client connects

    def count_for(self, principal: Principal) -> int:
        if principal.platform:
            return len(self.connections)
        return sum(1 for _, p in self.connections if p.tenant_id == principal.tenant_id)

    async def connect(self, websocket: WebSocket, principal: Principal) -> bool:
        if len(self.connections) >= MAX_WS_CONNECTIONS or \
                sum(1 for _, p in self.connections if p.key_id == principal.key_id) >= MAX_WS_PER_KEY:
            await _reject(websocket, CLOSE_TOO_MANY, "too_many_connections")
            return False
        self.connections.append((websocket, principal))
        await websocket.send_json({"type": "auth_ok", "tenant_id": principal.tenant_id, "platform": principal.platform})
        for event in self.buffers.get(principal.tenant_id, [])[-20:]:
            await websocket.send_json(event)
        return True

    def disconnect(self, websocket: WebSocket):
        self.connections = [(w, p) for w, p in self.connections if w is not websocket]

    async def broadcast(self, message: Dict[str, Any], tenant_id: str):
        """Deliver to the tenant's own connections (and platform admins), nobody else."""
        buf = self.buffers.setdefault(tenant_id, [])
        buf.append(message)
        if len(buf) > self.max_buffer_size:
            buf.pop(0)
        dead = []
        for ws, principal in list(self.connections):
            if not principal.can_see(tenant_id):
                continue
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """Real-time event stream for the caller's workspace."""
    principal = await _authenticate(websocket)
    if principal is None or not await manager.connect(websocket, principal):
        return
    manager.loop = asyncio.get_running_loop()
    verified = time.monotonic()
    try:
        while True:
            data = await websocket.receive_text()
            if len(data) > MAX_MESSAGE_CHARS:
                await websocket.close(code=CLOSE_TOO_BIG)
                break
            if time.monotonic() - verified > REAUTH_S:
                principal = await asyncio.to_thread(_still_valid, principal)
                if principal is None:
                    await _reject(websocket, CLOSE_UNAUTHORIZED, "key_revoked_or_expired")
                    break
                verified = time.monotonic()
            await websocket.send_json({"type": "heartbeat", "timestamp": datetime.utcnow().isoformat()})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)


def _still_valid(principal: Principal) -> Optional[Principal]:
    """Re-check a connected key (blocking). Revocation is by key hash, so look the key up by id."""
    from app.core.database import SessionLocal
    from app.core.deps import is_platform_admin
    from app.core.models_v3 import APIKey
    from app.core.security import RBACMiddleware, key_expired
    db = SessionLocal()
    try:
        key = db.query(APIKey).filter(APIKey.id == principal.key_id, APIKey.is_active == True).first()  # noqa: E712
        if not key or key_expired(key):
            return None
        if not RBACMiddleware.check_permission(key, db, "events", "read"):
            return None
        return Principal(str(key.id), str(key.tenant_id), is_platform_admin(key, db))
    finally:
        db.close()


_cache: Dict[str, tuple] = {}
_cache_lock = threading.Lock()


def _counts(principal: Principal) -> Dict[str, int]:
    """Event totals for the caller's scope, computed at most once per METRICS_CACHE_TTL_S per scope."""
    scope = "*" if principal.platform else principal.tenant_id
    with _cache_lock:
        hit = _cache.get(scope)
        if hit and time.monotonic() - hit[0] < METRICS_CACHE_TTL_S:
            return hit[1]
    from app.core.database import SessionLocal
    from app.core.models import Event
    from app.core.models_v2 import EntityWorkspace
    from app.core.models_v3 import EventV3
    db = SessionLocal()
    try:
        if principal.platform:
            v3, v1 = db.query(EventV3).count(), db.query(Event).count()
        else:
            linked = db.query(EntityWorkspace.entity_id).filter(EntityWorkspace.workspace_id == principal.tenant_id)
            v3 = db.query(EventV3).filter(EventV3.tenant_id == principal.tenant_id).count()
            v1 = db.query(Event).filter(Event.entity_id.in_(linked)).count()
    finally:
        db.close()
    out = {"total_events_v3": v3, "total_events_v1": v1, "total_events": v3 + v1}
    with _cache_lock:
        _cache[scope] = (time.monotonic(), out)
    return out


@router.websocket("/ws/metrics")
async def websocket_metrics(websocket: WebSocket):
    """Real-time metrics for the caller's workspace (global for a platform admin)."""
    principal = await _authenticate(websocket)
    if principal is None:
        return
    if len(manager.connections) >= MAX_WS_CONNECTIONS:
        await _reject(websocket, CLOSE_TOO_MANY, "too_many_connections")
        return
    await websocket.send_json({"type": "auth_ok", "tenant_id": principal.tenant_id, "platform": principal.platform})
    verified, prev, prev_t = time.monotonic(), None, None
    try:
        while True:
            if time.monotonic() - verified > REAUTH_S:
                principal = await asyncio.to_thread(_still_valid, principal)
                if principal is None:
                    await _reject(websocket, CLOSE_UNAUTHORIZED, "key_revoked_or_expired")
                    return
                verified = time.monotonic()
            counts = await asyncio.to_thread(_counts, principal)
            now = time.monotonic()
            rate = 0 if prev is None else max(0, round((counts["total_events"] - prev) / max(now - prev_t, 1e-6), 2))
            prev, prev_t = counts["total_events"], now
            await websocket.send_json({
                "type": "metrics_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": dict(counts, events_per_sec=rate, active_connections=manager.count_for(principal)),
            })
            await asyncio.sleep(METRICS_INTERVAL_S)
    except WebSocketDisconnect:
        pass


async def broadcast_event(event_data: Dict[str, Any], tenant_id: str):
    """Send an event to the WebSocket clients of one workspace (and platform admins).
    The tenant is required: there is no global broadcast."""
    await manager.broadcast({
        "type": "new_event",
        "timestamp": datetime.utcnow().isoformat(),
        "data": event_data
    }, str(tenant_id))


def publish_event(event_data: Dict[str, Any], tenant_id) -> None:
    """Push a "new_event" to a workspace's clients from synchronous code (the write routes run in a
    thread pool). Fire-and-forget: it never blocks the write and never raises. Only a summary is sent
    (ids and type, not the payload); clients fetch the rest through the normal, authorised endpoints.
    No client has connected yet means no loop and nothing to deliver."""
    loop = manager.loop
    if loop is None or loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(broadcast_event(event_data, str(tenant_id)), loop)
    except Exception as e:  # pragma: no cover - a failed push must not fail the write
        logger.error(f"publish_event failed: {e}")
