import hashlib
import hmac
import json
import os
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="Cryptographic API Governance Gateway", version="3.0.0")

ALLOWED_ACTIONS = frozenset({"read", "write", "execute"})
MAX_DRIFT_SECONDS = 300
MAX_BODY_BYTES = 64 * 1024
REPLAY_TTL_SECONDS = MAX_DRIFT_SECONDS * 2
REPLAY_MAX_ENTRIES = 100_000


class PolicyRequest(BaseModel):
    client_id: str
    action: str
    payload_checksum: str


def _load_keys() -> dict[str, bytes]:
    raw = os.environ.get("GATEWAY_KEYS")
    if not raw:
        raise RuntimeError('GATEWAY_KEYS env var required: JSON {"client_id": "secret"}')
    return {k: v.encode() for k, v in json.loads(raw).items()}


KEY_STORE: dict[str, bytes] = {}


class ReplayCache:
    """In-process (client_id, signature) seen-set with TTL. Per-instance: multi-replica
    deployments need a shared store (e.g. Redis SET NX EX) behind the same interface."""

    def __init__(self, ttl: float = REPLAY_TTL_SECONDS, max_entries: int = REPLAY_MAX_ENTRIES):
        self.ttl = ttl
        self.max_entries = max_entries
        self._seen: dict[tuple[str, str], float] = {}

    def check_and_add(self, client_id: str, signature: str) -> bool:
        """True if fresh (recorded); False if replay. Synchronous => atomic in the event loop."""
        now = time.monotonic()
        if len(self._seen) >= self.max_entries:
            self._seen = {k: t for k, t in self._seen.items() if t > now}
            if len(self._seen) >= self.max_entries:
                raise HTTPException(status_code=503, detail="Replay cache saturated.")
        key = (client_id, signature)
        exp = self._seen.get(key)
        if exp is not None and exp > now:
            return False
        self._seen[key] = now + self.ttl
        return True


REPLAY_CACHE = ReplayCache()


def get_keys() -> dict[str, bytes]:
    if not KEY_STORE:
        KEY_STORE.update(_load_keys())
    return KEY_STORE


async def verify_signature(request: Request) -> str:
    client_id = request.headers.get("X-Client-ID")
    signature = request.headers.get("X-Signature")
    timestamp = request.headers.get("X-Timestamp")
    if not client_id or not signature or not timestamp:
        raise HTTPException(status_code=401, detail="Missing required headers")
    try:
        req_time = float(timestamp)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format.")
    if abs(time.time() - req_time) > MAX_DRIFT_SECONDS:
        raise HTTPException(status_code=403, detail="Timestamp outside acceptable drift window.")
    secret = get_keys().get(client_id)
    if secret is None:
        raise HTTPException(status_code=403, detail="Invalid client identity.")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large.")
    computed = hmac.new(secret, body + timestamp.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, signature):
        raise HTTPException(status_code=401, detail="Signature verification failed.")
    if not REPLAY_CACHE.check_and_add(client_id, signature):
        raise HTTPException(status_code=409, detail="Replay detected.")
    return client_id


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/v1/policy/evaluate")
async def evaluate_policy(payload: PolicyRequest, client_id: str = Depends(verify_signature)):
    if payload.client_id != client_id:
        raise HTTPException(status_code=403, detail="Body client_id does not match authenticated identity.")
    if payload.action not in ALLOWED_ACTIONS:
        return {"status": "DENIED", "reason": "Action not permitted by policy."}
    token = hashlib.sha256(f"{client_id}:{payload.payload_checksum}".encode()).hexdigest()
    return {"status": "APPROVED", "client_id": client_id, "audit_token": token}
