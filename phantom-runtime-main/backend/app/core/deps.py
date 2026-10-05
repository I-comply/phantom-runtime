"""Shared FastAPI auth dependencies.

Centralizes the "require a valid API key with a given permission" check so
every route that creates, mutates, or executes something goes through the
same gate instead of each route file re-implementing (or forgetting) it.
"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.core.security import SecurityManager, RBACMiddleware
from app.core.models_v3 import APIKey


def require_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> APIKey:
    """Require a valid, active, non-expired API key. 401 if missing/invalid."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    api_key_obj = SecurityManager.verify_api_key(db, x_api_key)
    if not api_key_obj:
        raise HTTPException(status_code=401, detail="invalid or expired API key")
    return api_key_obj


def require_permission(resource: str, action: str):
    """Dependency factory: require an API key AND a specific resource:action grant."""

    def _check(
        api_key_obj: APIKey = Depends(require_api_key),
        db: Session = Depends(get_db),
    ) -> APIKey:
        if not RBACMiddleware.check_permission(api_key_obj, db, resource, action):
            raise HTTPException(status_code=403, detail=f"missing permission {resource}:{action}")
        return api_key_obj

    return _check
