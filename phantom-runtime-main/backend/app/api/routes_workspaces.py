from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any
from app.core.database import get_db
from app.core.multi_tenant import MultiTenantManager
from app.core.models_v2 import Workspace
from datetime import datetime

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

class WorkspaceCreate(BaseModel):
    name: str
    settings: Optional[Dict[str, Any]] = {}

class WorkspaceResponse(BaseModel):
    id: str
    name: str
    api_key: str
    settings: Dict[str, Any]
    created_at: datetime
    is_active: bool
    
    class Config:
        from_attributes = True

class EntityLinkRequest(BaseModel):
    entity_id: str

@router.post("/", response_model=WorkspaceResponse)
def create_workspace(workspace: WorkspaceCreate, db: Session = Depends(get_db)):
    """Create a new workspace"""
    ws = MultiTenantManager.create_workspace(
        db=db,
        name=workspace.name,
        settings=workspace.settings
    )
    return ws

@router.get("/me", response_model=WorkspaceResponse)
def get_current_workspace(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db)
):
    """Get workspace by API key"""
    workspace = MultiTenantManager.get_workspace_by_api_key(db, x_api_key)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found or inactive")
    return workspace

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
    
    link = MultiTenantManager.link_entity_to_workspace(
        db=db,
        workspace_id=str(workspace.id),
        entity_id=request.entity_id
    )
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
