from app.core.models_v2 import Plugin, PluginExecution
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import logging
import json

logger = logging.getLogger(__name__)

class PluginEngine:
    """Execute user-defined plugins on entity state"""
    
    @staticmethod
    def create_plugin(db: Session, name: str, code: str, plugin_type: str = "compute",
                     workspace_id: Optional[str] = None, config: dict = None) -> Plugin:
        """Create a new plugin"""
        plugin = Plugin(
            workspace_id=workspace_id,
            name=name,
            code=code,
            plugin_type=plugin_type,
            config=config or {}
        )
        db.add(plugin)
        db.commit()
        db.refresh(plugin)
        return plugin
    
    @staticmethod
    def execute_plugin(db: Session, plugin_id: str, entity_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a plugin on entity state"""
        plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
        
        if not plugin or not plugin.is_active:
            raise ValueError(f"Plugin {plugin_id} not found or inactive")
        
        # Create execution record
        execution = PluginExecution(
            plugin_id=plugin_id,
            entity_id=entity_id,
            status="running"
        )
        db.add(execution)
        db.commit()
        
        try:
            # Execute plugin code in sandboxed environment
            result = PluginEngine._execute_code(plugin.code, state, plugin.config)
            
            # Update execution record
            execution.status = "completed"
            execution.result = result
            execution.completed_at = datetime.now(timezone.utc)
            db.commit()
            
            return result
            
        except Exception as e:
            logger.error(f"Plugin execution failed: {e}")
            execution.status = "failed"
            execution.error = str(e)
            execution.completed_at = datetime.now(timezone.utc)
            db.commit()
            raise
    
    @staticmethod
    def _execute_code(code: str, state: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute plugin code with limited scope"""
        # Create safe execution environment
        safe_globals = {
            '__builtins__': {
                'len': len,
                'str': str,
                'int': int,
                'float': float,
                'dict': dict,
                'list': list,
                'sum': sum,
                'max': max,
                'min': min,
                'round': round,
            },
            'json': json,
        }
        
        safe_locals = {
            'state': state.copy(),  # Work on copy to prevent mutation
            'config': config,
        }
        
        # Execute code
        exec(code, safe_globals, safe_locals)
        
        # Return result from 'result' variable
        if 'result' not in safe_locals:
            raise ValueError("Plugin code must define 'result' variable")
        
        return safe_locals['result']
    
    @staticmethod
    def get_plugin_executions(db: Session, plugin_id: str, limit: int = 50):
        """Get recent executions for a plugin"""
        return db.query(PluginExecution).filter(
            PluginExecution.plugin_id == plugin_id
        ).order_by(PluginExecution.started_at.desc()).limit(limit).all()
