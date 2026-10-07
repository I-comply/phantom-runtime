from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from app.core.database import get_db
from app.core.plugin_engine import PluginEngine
from app.core.snapshot_manager import SnapshotManager
from app.core.deps import require_permission, is_platform_admin
from app.core.models_v2 import Plugin
from app.core.models_v3 import APIKey
from app.api.routes_state import _check_access
from datetime import datetime
import uuid

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

class PluginCreate(BaseModel):
    name: str
    description: Optional[str] = None
    code: str
    plugin_type: str = "compute"
    config: Optional[Dict[str, Any]] = {}
    workspace_id: Optional[str] = None

class PluginResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    plugin_type: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class PluginExecuteRequest(BaseModel):
    entity_id: str

def _get_plugin(db: Session, plugin_id: str, api_key_obj: APIKey) -> Plugin:
    """The plugin, or 404 (same answer for 'missing' and 'someone else's', so ids can't be probed).
    Non-admin keys only see plugins owned by their own workspace; plugins with no workspace
    (created before ownership was recorded) are admin-only."""
    try:
        pid = uuid.UUID(plugin_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="plugin not found")
    plugin = db.query(Plugin).filter(Plugin.id == pid).first()
    if plugin is None or (
        not is_platform_admin(api_key_obj, db) and str(plugin.workspace_id) != str(api_key_obj.tenant_id)
    ):
        raise HTTPException(status_code=404, detail="plugin not found")
    return plugin

@router.post("/", response_model=PluginResponse)
def create_plugin(
    plugin: PluginCreate,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("plugins", "write")),
):
    """Create a new plugin. Requires an API key with plugins:write.
    `code` is executed later via exec() (see PluginEngine._execute_code) — treat
    plugins:write as equivalent to granting arbitrary code execution, not a data-write."""
    # A plugin is owned by a workspace. An admin may create one for another workspace by naming it;
    # otherwise it belongs to the caller's own workspace. Never leave it ownerless.
    owner = plugin.workspace_id if (plugin.workspace_id and is_platform_admin(api_key_obj, db)) else str(api_key_obj.tenant_id)
    created_plugin = PluginEngine.create_plugin(
        db=db,
        name=plugin.name,
        code=plugin.code,
        plugin_type=plugin.plugin_type,
        workspace_id=owner,
        config=plugin.config
    )
    return PluginResponse(
        id=str(created_plugin.id), name=created_plugin.name,
        description=created_plugin.description, plugin_type=created_plugin.plugin_type,
        is_active=created_plugin.is_active, created_at=created_plugin.created_at,
    )

@router.post("/{plugin_id}/execute")
def execute_plugin(
    plugin_id: str,
    request: PluginExecuteRequest,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("plugins", "execute")),
):
    """Execute a plugin on an entity. Both the plugin and the entity must belong to the caller's
    workspace (admin keys are cross-tenant)."""
    plugin = _get_plugin(db, plugin_id, api_key_obj)
    _check_access(api_key_obj, db, request.entity_id)
    workspace_id = None if is_platform_admin(api_key_obj, db) else str(api_key_obj.tenant_id)
    try:
        # Get current state
        state = SnapshotManager.reconstruct_with_snapshot(db, request.entity_id, workspace_id)
        
        # Execute plugin
        result = PluginEngine.execute_plugin(
            db=db,
            plugin_id=str(plugin.id),
            entity_id=request.entity_id,
            state=state
        )
        
        return {
            "status": "success",
            "entity_id": request.entity_id,
            "plugin_id": str(plugin.id),
            "result": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{plugin_id}/executions")
def get_plugin_executions(
    plugin_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    api_key_obj: APIKey = Depends(require_permission("plugins", "read")),
):
    """Get execution history for a plugin (the caller's own workspace's plugins only)"""
    plugin = _get_plugin(db, plugin_id, api_key_obj)
    limit = max(1, min(limit, 500))
    executions = PluginEngine.get_plugin_executions(db, str(plugin.id), limit)
    return {
        "plugin_id": str(plugin.id),
        "executions": [
            {
                "id": str(ex.id),
                "entity_id": ex.entity_id,
                "status": ex.status,
                "result": ex.result,
                "error": ex.error,
                "started_at": ex.started_at,
                "completed_at": ex.completed_at
            }
            for ex in executions
        ]
    }
