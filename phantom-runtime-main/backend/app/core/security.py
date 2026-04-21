from sqlalchemy.orm import Session
from app.core.models_v3 import APIKey, Role
from typing import Optional
import hashlib
import secrets
import hmac
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

class SecurityManager:
    """HMAC signing, RBAC, and API key management"""
    
    @staticmethod
    def generate_api_key() -> str:
        """Generate cryptographically secure API key"""
        return 'sk_' + secrets.token_urlsafe(32)
    
    @staticmethod
    def hash_key(key: str) -> str:
        """Hash API key for storage"""
        return hashlib.sha256(key.encode()).hexdigest()
    
    @staticmethod
    def create_api_key(
        db: Session,
        tenant_id: str,
        role_name: str,
        name: str,
        expires_at: Optional[datetime] = None
    ) -> tuple[APIKey, str]:
        """Create new API key"""
        
        # Get role
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            raise ValueError(f"Role {role_name} not found")
        
        # Generate key
        key = SecurityManager.generate_api_key()
        key_hash = SecurityManager.hash_key(key)
        
        api_key = APIKey(
            key_hash=key_hash,
            tenant_id=tenant_id,
            role_id=role.id,
            name=name,
            expires_at=expires_at
        )
        
        db.add(api_key)
        db.commit()
        db.refresh(api_key)
        
        return api_key, key  # Return plaintext key only once
    
    @staticmethod
    def verify_api_key(db: Session, key: str) -> Optional[APIKey]:
        """Verify API key and return associated record"""
        key_hash = SecurityManager.hash_key(key)
        
        api_key = db.query(APIKey).filter(
            APIKey.key_hash == key_hash,
            APIKey.is_active == True
        ).first()
        
        if not api_key:
            return None
        
        # Check expiration
        if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
            return None
        
        # Update last used
        api_key.last_used_at = datetime.now(timezone.utc)
        db.commit()
        
        return api_key
    
    @staticmethod
    def compute_hmac(data: str, secret: str) -> str:
        """Compute HMAC-SHA256 signature"""
        return hmac.new(
            secret.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
    
    @staticmethod
    def verify_hmac(data: str, signature: str, secret: str) -> bool:
        """Verify HMAC signature"""
        expected = SecurityManager.compute_hmac(data, secret)
        return hmac.compare_digest(signature, expected)
    
    @staticmethod
    def sign_event(event_data: dict, secret: str) -> str:
        """Sign event data with HMAC"""
        import json
        canonical = json.dumps(event_data, sort_keys=True)
        return SecurityManager.compute_hmac(canonical, secret)
    
    @staticmethod
    def initialize_roles(db: Session):
        """Initialize default RBAC roles"""
        roles_config = {
            'admin': {
                'events': ['read', 'write', 'delete'],
                'strategies': ['read', 'write', 'execute', 'delete'],
                'workspaces': ['read', 'write', 'delete'],
                'api_keys': ['read', 'write', 'delete']
            },
            'agent': {
                'events': ['read', 'write'],
                'strategies': ['read', 'execute'],
                'workspaces': ['read']
            },
            'viewer': {
                'events': ['read'],
                'strategies': ['read'],
                'workspaces': ['read']
            },
            'system': {
                'events': ['read', 'write'],
                'strategies': ['execute'],
                'workspaces': ['read']
            }
        }
        
        for role_name, permissions in roles_config.items():
            existing = db.query(Role).filter(Role.name == role_name).first()
            if not existing:
                role = Role(
                    name=role_name,
                    permissions=permissions
                )
                db.add(role)
        
        db.commit()
        logger.info("RBAC roles initialized")

class RBACMiddleware:
    """Role-based access control middleware"""
    
    @staticmethod
    def check_permission(api_key: APIKey, db: Session, resource: str, action: str) -> bool:
        """Check if API key has permission for resource:action"""
        role = db.query(Role).filter(Role.id == api_key.role_id).first()
        
        if not role:
            return False
        
        permissions = role.permissions.get(resource, [])
        return action in permissions
    
    @staticmethod
    def require_permission(api_key: APIKey, db: Session, resource: str, action: str):
        """Raise exception if permission not granted"""
        if not RBACMiddleware.check_permission(api_key, db, resource, action):
            raise PermissionError(f"Insufficient permissions for {resource}:{action}")
