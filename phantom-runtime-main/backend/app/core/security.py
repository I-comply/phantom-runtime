from sqlalchemy.orm import Session
from app.core.models_v3 import APIKey, Role
from typing import Optional
import hashlib
import secrets
import hmac
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

def key_expired(api_key) -> bool:
    """expires_at is a naive UTC column (the driver returns it without tzinfo); comparing it with an
    aware now() raised TypeError, so any key with an expiry turned into a 500."""
    exp = api_key.expires_at
    if exp is None:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < datetime.now(timezone.utc)


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
        if key_expired(api_key):
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
                'plugins': ['read', 'write', 'execute', 'delete'],
                'defi': ['read', 'write'],
                'snapshots': ['read', 'write'],
                'workspaces': ['read', 'write', 'delete'],
                'api_keys': ['read', 'write', 'delete']
            },
            'agent': {
                'events': ['read', 'write'],
                'strategies': ['read', 'execute'],
                'plugins': ['read', 'execute'],
                'defi': ['read', 'write'],
                'snapshots': ['read', 'write'],
                'workspaces': ['read']
            },
            'viewer': {
                'events': ['read'],
                'strategies': ['read'],
                'plugins': ['read'],
                'defi': ['read'],
                'snapshots': ['read'],
                'workspaces': ['read']
            },
            'system': {
                'events': ['read', 'write'],
                'strategies': ['execute'],
                'plugins': ['execute'],
                'defi': ['read', 'write'],
                'snapshots': ['read', 'write'],
                'workspaces': ['read']
            }
        }

        for role_name, permissions in roles_config.items():
            existing = db.query(Role).filter(Role.name == role_name).first()
            if not existing:
                role = Role(name=role_name, permissions=permissions)
                db.add(role)
            else:
                # Merge in any resources this version of the app knows about that
                # the stored row predates (e.g. upgrading onto a running deployment
                # that minted its roles before 'plugins'/'defi'/'snapshots' existed).
                # Never removes or narrows a permission an operator already granted.
                merged = dict(existing.permissions or {})
                changed = False
                for resource, actions in permissions.items():
                    if resource not in merged:
                        merged[resource] = actions
                        changed = True
                if changed:
                    existing.permissions = merged
                    logger.info(f"RBAC role '{role_name}' gained new resource grants: {list(merged.keys())}")

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
