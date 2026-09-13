"""
Role-Based Access Control (RBAC) Implementation
Manages permissions and role-based authorization for multi-tenant security
"""

import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from .models import User, Role, Permission, RoleType
from ..core.exceptions import AuthorizationError, TenantIsolationError

logger = logging.getLogger(__name__)

class RoleBasedAccessControl:
    """Role-based access control system for multi-tenant security"""
    
    def __init__(self):
        self.permission_cache = {}
    
    def check_permission(self, session: Session, user_id: str, permission: str, 
                        resource_id: str = None, tenant_id: str = None) -> bool:
        """Check if user has specific permission"""
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active:
                return False
            
            # Check tenant isolation if tenant_id is provided
            if tenant_id and user.tenant_id != tenant_id:
                raise TenantIsolationError(f"User {user_id} cannot access tenant {tenant_id}")
            
            # Admin has all permissions
            if user.role == RoleType.ADMIN.value:
                return True
            
            # Tenant admin has full permissions within their tenant
            if user.role == RoleType.TENANT_ADMIN.value and user.tenant_id == tenant_id:
                return True
            
            # Check specific permissions for user role
            return self._check_role_permission(user.role, permission, resource_id)
            
        except Exception as e:
            logger.error(f"Permission check failed for user {user_id}: {e}")
            return False
    
    def _check_role_permission(self, role: str, permission: str, resource_id: str = None) -> bool:
        """Check if role has specific permission"""
        role_permissions = {
            RoleType.ADMIN.value: ["*"],  # All permissions
            RoleType.TENANT_ADMIN.value: [
                "containers:*", "users:*", "quotas:*", "audit:read", "security:read"
            ],
            RoleType.USER.value: [
                "containers:create", "containers:read", "containers:update", "containers:delete",
                "quotas:read", "audit:read_own"
            ],
            RoleType.READONLY.value: [
                "containers:read", "quotas:read"
            ]
        }
        
        permissions = role_permissions.get(role, [])
        
        # Check wildcard permission
        if "*" in permissions:
            return True
        
        # Check exact permission match
        if permission in permissions:
            return True
        
        # Check category wildcard (e.g., "containers:*")
        category = permission.split(":")[0]
        if f"{category}:*" in permissions:
            return True
        
        return False
    
    def get_user_permissions(self, session: Session, user_id: str) -> List[str]:
        """Get all permissions for a user"""
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active:
                return []
            
            role_permissions = {
                RoleType.ADMIN.value: ["*"],
                RoleType.TENANT_ADMIN.value: [
                    "containers:*", "users:*", "quotas:*", "audit:read", "security:read"
                ],
                RoleType.USER.value: [
                    "containers:create", "containers:read", "containers:update", "containers:delete",
                    "quotas:read", "audit:read_own"
                ],
                RoleType.READONLY.value: [
                    "containers:read", "quotas:read"
                ]
            }
            
            return role_permissions.get(user.role, [])
            
        except Exception as e:
            logger.error(f"Failed to get permissions for user {user_id}: {e}")
            return []
    
    def enforce_tenant_isolation(self, session: Session, user_id: str, 
                                target_tenant_id: str) -> bool:
        """Enforce tenant isolation for operations"""
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active:
                raise AuthorizationError("Invalid user")
            
            # System admin can access any tenant
            if user.role == RoleType.ADMIN.value:
                return True
            
            # Users can only access their own tenant
            if user.tenant_id != target_tenant_id:
                raise TenantIsolationError(
                    f"User {user_id} cannot access tenant {target_tenant_id}"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Tenant isolation check failed: {e}")
            raise
    
    def validate_role_transition(self, current_role: str, new_role: str, 
                                requesting_user_role: str) -> bool:
        """Validate if role transition is allowed"""
        role_hierarchy = {
            RoleType.ADMIN.value: 4,
            RoleType.TENANT_ADMIN.value: 3,
            RoleType.USER.value: 2,
            RoleType.READONLY.value: 1
        }
        
        current_level = role_hierarchy.get(current_role, 0)
        new_level = role_hierarchy.get(new_role, 0)
        requesting_level = role_hierarchy.get(requesting_user_role, 0)
        
        # Can only assign roles at or below your level
        return requesting_level >= max(current_level, new_level)
    
    def get_accessible_tenants(self, session: Session, user_id: str) -> List[str]:
        """Get list of tenant IDs accessible to user"""
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active:
                return []
            
            # System admin can access all tenants
            if user.role == RoleType.ADMIN.value:
                from .models import Tenant
                tenants = session.query(Tenant).filter(Tenant.is_active == True).all()
                return [tenant.id for tenant in tenants]
            
            # Other users can only access their own tenant
            return [user.tenant_id]
            
        except Exception as e:
            logger.error(f"Failed to get accessible tenants for user {user_id}: {e}")
            return []
    
    def audit_permission_check(self, session: Session, user_id: str, 
                              permission: str, resource_id: str = None, 
                              granted: bool = False) -> None:
        """Audit permission check for security monitoring"""
        try:
            from .models import AuditLog
            from datetime import datetime
            
            audit_log = AuditLog(
                tenant_id=None,  # Will be filled by the calling context
                user_id=user_id,
                action="permission_check",
                resource_type="rbac",
                resource_id=resource_id or "system",
                details=f'{{"permission": "{permission}", "granted": {granted}}}',
                ip_address=None,  # Will be filled by the calling context
                user_agent=None,
                status="success" if granted else "denied",
                severity="info" if granted else "warning",
                timestamp=datetime.utcnow()
            )
            
            session.add(audit_log)
            
        except Exception as e:
            logger.error(f"Failed to audit permission check: {e}")