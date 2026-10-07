from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request
from app.core.config import settings
from app.core.reconciler_http import TOKEN_HEADER, token_valid

router = APIRouter(prefix="/api/reconciler", tags=["reconciler"])


def _replica(request: Request, token: Optional[str]):
    if not settings.RECONCILER_ENABLED or not settings.RECONCILER_SHARED_SECRET:
        raise HTTPException(status_code=404, detail="not found")
    if not token_valid(token, settings.RECONCILER_SHARED_SECRET):
        raise HTTPException(status_code=401, detail="invalid reconciler token")
    return request.app.state.replica_state


@router.get("/digest")
async def digest(request: Request, x_reconciler_token: Optional[str] = Header(None, alias=TOKEN_HEADER)):
    r = _replica(request, x_reconciler_token)
    return {"node_id": r.node_id, "digest": r.digest(), "clock": r.clock.to_dict()}


@router.get("/snapshot")
async def snapshot(request: Request, x_reconciler_token: Optional[str] = Header(None, alias=TOKEN_HEADER)):
    return _replica(request, x_reconciler_token).snapshot()
