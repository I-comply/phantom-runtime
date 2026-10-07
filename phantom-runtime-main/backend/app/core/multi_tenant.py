from sqlalchemy.orm import Session
from app.core.models_v2 import Workspace, EntityWorkspace
from typing import Optional, Tuple
import hashlib
import secrets
import string

class EntityAlreadyClaimed(Exception):
    """The entity is already linked to a different workspace."""


class MultiTenantManager:
    @staticmethod
    def generate_api_key() -> str:
        """Generate a secure API key (plaintext, shown to the caller once)"""
        alphabet = string.ascii_letters + string.digits
        return 'pk_' + ''.join(secrets.choice(alphabet) for _ in range(32))

    @staticmethod
    def hash_key(key: str) -> str:
        """Hash a workspace API key for storage (same scheme as SecurityManager.hash_key)"""
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def create_workspace(db: Session, name: str, settings: dict = None) -> Tuple[Workspace, str]:
        """Create a new workspace. Returns (workspace, plaintext_api_key) — the plaintext
        key is never stored and is only ever available from this return value."""
        api_key = MultiTenantManager.generate_api_key()
        workspace = Workspace(
            name=name,
            api_key=MultiTenantManager.hash_key(api_key),
            settings=settings or {}
        )
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        return workspace, api_key

    @staticmethod
    def get_workspace_by_api_key(db: Session, api_key: str) -> Optional[Workspace]:
        """Get workspace by API key (compares against the stored hash)"""
        return db.query(Workspace).filter(
            Workspace.api_key == MultiTenantManager.hash_key(api_key),
            Workspace.is_active == True
        ).first()
    
    @staticmethod
    def link_entity_to_workspace(db: Session, workspace_id: str, entity_id: str) -> EntityWorkspace:
        """Link an entity to a workspace. First claimant wins (same rule as EventStore.claim_entity):
        raises EntityAlreadyClaimed if the entity is linked to any other workspace. Without this,
        any tenant could link another tenant's entity_id to itself and read its events and state."""
        from app.core.event_store import EventStore
        EventStore.lock_entity(db, entity_id)  # two simultaneous claimants must not both win
        owner = db.query(EntityWorkspace).filter(
            EntityWorkspace.entity_id == entity_id,
            EntityWorkspace.workspace_id != workspace_id
        ).first()
        if owner:
            db.rollback()
            raise EntityAlreadyClaimed(entity_id)
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
