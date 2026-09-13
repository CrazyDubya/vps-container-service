"""
Authentication and Authorization Managers
Secure JWT-based authentication with multi-tenant isolation
"""

import jwt
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet
import logging

from .models import User, Tenant, UserSession, AuditLog, RoleType
from ..core.exceptions import AuthenticationError, AuthorizationError, TenantIsolationError

logger = logging.getLogger(__name__)

class AuthenticationManager:
    """Handles user authentication with security best practices"""
    
    def __init__(self, jwt_secret: str, encryption_key: Optional[bytes] = None):
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = "HS256"
        self.session_duration = timedelta(hours=8)
        self.refresh_duration = timedelta(days=30)
        
        # Encryption for sensitive data
        self.cipher = Fernet(encryption_key or Fernet.generate_key())
    
    def authenticate_user(self, db: Session, email: str, password: str, 
                         ip_address: str = None, user_agent: str = None) -> Dict[str, Any]:
        """Authenticate user and create session"""
        try:
            # Find user by email
            user = db.query(User).filter(
                User.email == email.lower(),
                User.is_active == True
            ).first()
            
            if not user or not user.check_password(password):
                self._log_auth_failure(db, email, ip_address, "invalid_credentials")
                db.commit()  # Commit the audit log before raising exception
                raise AuthenticationError("Invalid email or password")
            
            # Check tenant is active
            if not user.tenant.is_active:
                self._log_auth_failure(db, email, ip_address, "tenant_inactive")
                db.commit()  # Commit the audit log before raising exception
                raise AuthenticationError("Account is suspended")
            
            # Update last login
            user.last_login = datetime.now(timezone.utc)
            
            # Create session
            session_token = self._create_session(db, user, ip_address, user_agent)
            
            # Generate JWT
            jwt_token = self._create_jwt_token(user)
            
            # Log successful authentication
            self._log_auth_success(db, user, ip_address)
            
            db.commit()
            
            return {
                "user_id": user.id,
                "email": user.email,
                "tenant_id": user.tenant_id,
                "role": user.role,
                "jwt_token": jwt_token,
                "session_token": session_token,
                "expires_at": datetime.now(timezone.utc) + self.session_duration
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Authentication failed for {email}: {str(e)}")
            raise
    
    def authenticate_api_key(self, db: Session, api_key: str) -> Dict[str, Any]:
        """Authenticate using API key"""
        try:
            # Hash the provided API key and find matching user
            api_key_hash = self._hash_api_key(api_key)
            user = db.query(User).filter(
                User.api_key_hash == api_key_hash,
                User.is_active == True
            ).first()
            
            if not user:
                raise AuthenticationError("Invalid API key")
            
            if not user.tenant.is_active:
                raise AuthenticationError("Account is suspended")
            
            return {
                "user_id": user.id,
                "email": user.email,
                "tenant_id": user.tenant_id,
                "role": user.role,
                "auth_method": "api_key"
            }
            
        except Exception as e:
            logger.error(f"API key authentication failed: {str(e)}")
            raise
    
    def verify_jwt_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            
            # Check expiration
            if datetime.fromtimestamp(payload['exp'], timezone.utc) < datetime.now(timezone.utc):
                raise AuthenticationError("Token has expired")
            
            return payload
            
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except jwt.InvalidTokenError:
            raise AuthenticationError("Invalid token")
    
    def refresh_token(self, db: Session, refresh_token: str) -> Dict[str, Any]:
        """Refresh JWT token using refresh token"""
        try:
            # Find active session
            session = db.query(UserSession).filter(
                UserSession.session_token == refresh_token,
                UserSession.is_active == True,
                UserSession.expires_at > datetime.now(timezone.utc)
            ).first()
            
            if not session:
                raise AuthenticationError("Invalid refresh token")
            
            user = session.user
            if not user.is_active or not user.tenant.is_active:
                raise AuthenticationError("Account is suspended")
            
            # Generate new JWT
            jwt_token = self._create_jwt_token(user)
            
            return {
                "user_id": user.id,
                "jwt_token": jwt_token,
                "expires_at": datetime.now(timezone.utc) + self.session_duration
            }
            
        except Exception as e:
            logger.error(f"Token refresh failed: {str(e)}")
            raise
    
    def logout(self, db: Session, session_token: str):
        """Logout user and invalidate session"""
        try:
            session = db.query(UserSession).filter(
                UserSession.session_token == session_token
            ).first()
            
            if session:
                session.is_active = False
                db.commit()
                
        except Exception as e:
            logger.error(f"Logout failed: {str(e)}")
            db.rollback()
    
    def _create_session(self, db: Session, user: User, ip_address: str, user_agent: str) -> str:
        """Create user session"""
        session_token = secrets.token_urlsafe(32)
        
        session = UserSession(
            user_id=user.id,
            session_token=session_token,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=datetime.now(timezone.utc) + self.refresh_duration
        )
        
        db.add(session)
        return session_token
    
    def _create_jwt_token(self, user: User) -> str:
        """Create JWT token with user claims"""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user.id,
            "email": user.email,
            "tenant_id": user.tenant_id,
            "role": user.role,
            "iat": now,
            "exp": now + self.session_duration
        }
        
        return jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
    
    def _hash_api_key(self, api_key: str) -> str:
        """Hash API key for storage"""
        import hashlib
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    def _log_auth_success(self, db: Session, user: User, ip_address: str):
        """Log successful authentication"""
        audit_log = AuditLog(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action="login",
            resource_type="user",
            resource_id=user.id,
            ip_address=ip_address,
            severity="info",
            status="success"
        )
        db.add(audit_log)
    
    def _log_auth_failure(self, db: Session, email: str, ip_address: str, reason: str):
        """Log failed authentication"""
        audit_log = AuditLog(
            action="login_failed",
            resource_type="user",
            ip_address=ip_address,
            details=f"Failed login attempt for {email}: {reason}",
            severity="warning",
            status="failure"
        )
        db.add(audit_log)

class AuthorizationManager:
    """Handles authorization and tenant isolation"""
    
    def __init__(self):
        self.role_hierarchy = {
            RoleType.PLATFORM_ADMIN: 4,
            RoleType.TENANT_ADMIN: 3,
            RoleType.USER: 2,
            RoleType.READONLY: 1
        }
    
    def check_permission(self, user_context: Dict[str, Any], action: str, 
                        resource_type: str, resource_tenant_id: str = None,
                        resource_user_id: str = None) -> bool:
        """Check if user has permission for action on resource"""
        try:
            user_role = RoleType(user_context["role"])
            user_tenant_id = user_context["tenant_id"]
            user_id = user_context["user_id"]
            
            # Platform admins can do everything
            if user_role == RoleType.PLATFORM_ADMIN:
                return True
            
            # Check tenant isolation - users can only access their tenant's resources
            if resource_tenant_id and resource_tenant_id != user_tenant_id:
                raise TenantIsolationError(f"Cross-tenant access denied: user tenant {user_tenant_id}, resource tenant {resource_tenant_id}")
            
            # Tenant admins can access all resources in their tenant
            if user_role == RoleType.TENANT_ADMIN and resource_tenant_id == user_tenant_id:
                return self._check_tenant_admin_permission(action, resource_type)
            
            # Regular users can only access their own resources
            if user_role == RoleType.USER:
                if resource_user_id and resource_user_id != user_id:
                    return False
                return self._check_user_permission(action, resource_type)
            
            # ReadOnly users can only view their own resources
            if user_role == RoleType.READONLY:
                if resource_user_id and resource_user_id != user_id:
                    return False
                return action == "read"
            
            return False
            
        except Exception as e:
            logger.error(f"Authorization check failed: {str(e)}")
            raise AuthorizationError(str(e))
    
    def enforce_tenant_isolation(self, user_context: Dict[str, Any], resource_tenant_id: str):
        """Enforce strict tenant isolation"""
        user_tenant_id = user_context["tenant_id"]
        user_role = RoleType(user_context["role"])
        
        # Platform admins can access any tenant
        if user_role == RoleType.PLATFORM_ADMIN:
            return
        
        # All other users must stay within their tenant
        if resource_tenant_id != user_tenant_id:
            raise TenantIsolationError(
                f"Tenant isolation violation: user {user_context['user_id']} "
                f"from tenant {user_tenant_id} tried to access tenant {resource_tenant_id}"
            )
    
    def get_user_permissions(self, user_context: Dict[str, Any]) -> List[str]:
        """Get list of permissions for user"""
        user_role = RoleType(user_context["role"])
        
        permissions = []
        
        if user_role == RoleType.PLATFORM_ADMIN:
            permissions = [
                "containers:*:*", "users:*:*", "tenants:*:*", 
                "quotas:*:*", "security:*:*", "audit:*:*"
            ]
        elif user_role == RoleType.TENANT_ADMIN:
            permissions = [
                "containers:*:tenant", "users:*:tenant", "quotas:read:tenant",
                "audit:read:tenant", "security:read:tenant"
            ]
        elif user_role == RoleType.USER:
            permissions = [
                "containers:*:own", "users:read:own", "quotas:read:own"
            ]
        elif user_role == RoleType.READONLY:
            permissions = [
                "containers:read:own", "users:read:own", "quotas:read:own"
            ]
        
        return permissions
    
    def _check_tenant_admin_permission(self, action: str, resource_type: str) -> bool:
        """Check permissions for tenant admin"""
        # Tenant admins can manage most resources in their tenant
        admin_permissions = {
            "containers": ["create", "read", "update", "delete"],
            "users": ["create", "read", "update", "delete"],
            "quotas": ["read"],
            "audit": ["read"],
            "security": ["read"]
        }
        
        return action in admin_permissions.get(resource_type, [])
    
    def _check_user_permission(self, action: str, resource_type: str) -> bool:
        """Check permissions for regular user"""
        # Regular users can manage their own containers
        user_permissions = {
            "containers": ["create", "read", "update", "delete"],
            "users": ["read"],
            "quotas": ["read"]
        }
        
        return action in user_permissions.get(resource_type, [])