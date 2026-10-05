from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from app.core.database import get_db
from app.core.plugin_engine import PluginEngine
from app.core.snapshot_manager import SnapshotManager
from app.core.deps import require_permission
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

@router.post("/", response_model=PluginResponse)
def create_plugin(
    plugin: PluginCreate,
    db: Session = Depends(get_db),
    _auth=Depends(require_permission("plugins", "write")),
):
    """Create a new plugin. Requires an API key with plugins:write.
    `code` is executed later via exec() (see PluginEngine._execute_code) — treat
    plugins:write as equivalent to granting arbitrary code execution, not a data-write."""
    created_plugin = PluginEngine.create_plugin(
        db=db,
        name=plugin.name,
        code=plugin.code,
        plugin_type=plugin.plugin_type,
        workspace_id=plugin.workspace_id,
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
    _auth=Depends(require_permission("plugins", "execute")),
):
    """Execute a plugin on an entity"""
    try:
        # Get current state
        state = SnapshotManager.reconstruct_with_snapshot(db, request.entity_id)
        
        # Execute plugin
        result = PluginEngine.execute_plugin(
            db=db,
            plugin_id=plugin_id,
            entity_id=request.entity_id,
            state=state
        )
        
        return {
            "status": "success",
            "entity_id": request.entity_id,
            "plugin_id": plugin_id,
            "result": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{plugin_id}/executions")
def get_plugin_executions(plugin_id: str, limit: int = 50, db: Session = Depends(get_db)):
    """Get execution history for a plugin"""
    executions = PluginEngine.get_plugin_executions(db, plugin_id, limit)
    return {
        "plugin_id": plugin_id,
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
