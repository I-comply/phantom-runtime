import hmac
import json
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any
from app.core.config import settings as app_settings
from app.core.database import get_db
from app.core.deps import is_platform_admin
from app.core.security import SecurityManager
from app.core.multi_tenant import MultiTenantManager, EntityAlreadyClaimed
from app.core.models_v2 import Workspace
from datetime import datetime

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

MAX_SETTINGS_BYTES = 8192

class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    settings: Optional[Dict[str, Any]] = {}

    @field_validator("settings")
    @classmethod
    def _settings_small(cls, v):
        if v is not None and len(json.dumps(v)) > MAX_SETTINGS_BYTES:
            raise ValueError(f"settings must be at most {MAX_SETTINGS_BYTES} bytes of JSON")
        return v

class WorkspaceResponse(BaseModel):
    id: str
    name: str
    settings: Dict[str, Any]
    created_at: datetime
    is_active: bool

    class Config:
        from_attributes = True

class WorkspaceCreateResponse(WorkspaceResponse):
    api_key: str  # plaintext, only ever present in this one response

class EntityLinkRequest(BaseModel):
    entity_id: str

def require_workspace_creator(
    x_bootstrap_key: Optional[str] = Header(None, alias="X-Bootstrap-Key"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    """Creating a workspace takes the bootstrap key or a platform admin API key. It used to be open
    to anyone, which let anyone create workspaces (and workspace keys) without limit."""
    if x_bootstrap_key and app_settings.BOOTSTRAP_ADMIN_KEY and hmac.compare_digest(
            x_bootstrap_key, app_settings.BOOTSTRAP_ADMIN_KEY):
        return
    if x_api_key:
        key = SecurityManager.verify_api_key(db, x_api_key)
        if key and is_platform_admin(key, db):
            return
        if key:
            raise HTTPException(status_code=403, detail="creating a workspace requires a platform admin key")
    raise HTTPException(status_code=401, detail="requires X-Bootstrap-Key or a platform admin X-API-Key")

@router.post("/", response_model=WorkspaceCreateResponse, status_code=201,
             dependencies=[Depends(require_workspace_creator)])
def create_workspace(workspace: WorkspaceCreate, db: Session = Depends(get_db)):
    """Create a new workspace (bootstrap key or platform admin key required). The API key is
    returned once, in plaintext, and never stored or retrievable again — only its hash is kept
    server-side."""
    ws, plaintext_key = MultiTenantManager.create_workspace(
        db=db,
        name=workspace.name,
        settings=workspace.settings
    )
    return WorkspaceCreateResponse(
        id=str(ws.id), name=ws.name, settings=ws.settings,
        created_at=ws.created_at, is_active=ws.is_active, api_key=plaintext_key,
    )

@router.get("/me", response_model=WorkspaceResponse)
def get_current_workspace(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db)
):
    """Get workspace by API key"""
    workspace = MultiTenantManager.get_workspace_by_api_key(db, x_api_key)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found or inactive")
    return WorkspaceResponse(
        id=str(workspace.id), name=workspace.name, settings=workspace.settings,
        created_at=workspace.created_at, is_active=workspace.is_active,
    )

@router.post("/me/entities", status_code=201)
def link_entity_to_workspace(
    request: EntityLinkRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db)
):
    """Link an entity to current workspace"""
    workspace = MultiTenantManager.get_workspace_by_api_key(db, x_api_key)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    try:
        link = MultiTenantManager.link_entity_to_workspace(
            db=db,
            workspace_id=str(workspace.id),
            entity_id=request.entity_id
        )
    except EntityAlreadyClaimed:
        raise HTTPException(status_code=409, detail="entity is already linked to another workspace")
    return {"status": "linked", "entity_id": request.entity_id}

@router.get("/me/entities")
def get_workspace_entities(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db)
):
    """Get all entities for current workspace"""
    workspace = MultiTenantManager.get_workspace_by_api_key(db, x_api_key)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    entities = MultiTenantManager.get_workspace_entities(db, str(workspace.id))
    return {"workspace_id": str(workspace.id), "entities": entities}
