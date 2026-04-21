from sqlalchemy.orm import Session
from app.core.models_v2 import Workspace, EntityWorkspace
from typing import Optional
import secrets
import string

class MultiTenantManager:
    @staticmethod
    def generate_api_key() -> str:
        """Generate a secure API key"""
        alphabet = string.ascii_letters + string.digits
        return 'pk_' + ''.join(secrets.choice(alphabet) for _ in range(32))
    
    @staticmethod
    def create_workspace(db: Session, name: str, settings: dict = None) -> Workspace:
        """Create a new workspace"""
        api_key = MultiTenantManager.generate_api_key()
        workspace = Workspace(
            name=name,
            api_key=api_key,
            settings=settings or {}
        )
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        return workspace
    
    @staticmethod
    def get_workspace_by_api_key(db: Session, api_key: str) -> Optional[Workspace]:
        """Get workspace by API key"""
        return db.query(Workspace).filter(
            Workspace.api_key == api_key,
            Workspace.is_active == True
        ).first()
    
    @staticmethod
    def link_entity_to_workspace(db: Session, workspace_id: str, entity_id: str) -> EntityWorkspace:
        """Link an entity to a workspace"""
        # Check if link already exists
        existing = db.query(EntityWorkspace).filter(
            EntityWorkspace.workspace_id == workspace_id,
            EntityWorkspace.entity_id == entity_id
        ).first()
        
        if existing:
            return existing
        
        link = EntityWorkspace(
            workspace_id=workspace_id,
            entity_id=entity_id
        )
        db.add(link)
        db.commit()
        db.refresh(link)
        return link
    
    @staticmethod
    def get_workspace_entities(db: Session, workspace_id: str) -> list:
        """Get all entities for a workspace"""
        links = db.query(EntityWorkspace).filter(
            EntityWorkspace.workspace_id == workspace_id
        ).all()
        return [link.entity_id for link in links]
    
    @staticmethod
    def verify_entity_access(db: Session, workspace_id: str, entity_id: str) -> bool:
        """Verify that a workspace has access to an entity"""
        link = db.query(EntityWorkspace).filter(
            EntityWorkspace.workspace_id == workspace_id,
            EntityWorkspace.entity_id == entity_id
        ).first()
        return link is not None
