"""
IAM Database Models - Multi-Tenant Security Architecture
Defines users, tenants, roles, permissions with strict isolation
"""

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, validates
from datetime import datetime, timezone
from enum import Enum
import uuid
import bcrypt

Base = declarative_base()

class RoleType(Enum):
    """User role types with hierarchical permissions"""
    PLATFORM_ADMIN = "platform_admin"     # Global access
    TENANT_ADMIN = "tenant_admin"          # Single tenant scope
    USER = "user"                          # Own resources only  
    READONLY = "readonly"                  # View own containers only

class ResourceType(Enum):
    """Resource types for quota management"""
    FIRECRACKER_VM = "firecracker_vm"
    LXC_CONTAINER = "lxc_container"
    MEMORY_GB = "memory_gb"
    CPU_CORES = "cpu_cores"
    GPU_HOURS = "gpu_hours"
    STORAGE_GB = "storage_gb"
    NETWORK_MBPS = "network_mbps"

class Tenant(Base):
    """Tenant model - Organization-level isolation"""
    __tablename__ = 'tenants'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    domain = Column(String(255), unique=True, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)
    
    # Billing and contact info
    billing_email = Column(String(255), nullable=True)
    contact_name = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    
    # Relationships
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    quotas = relationship("TenantQuota", back_populates="tenant", cascade="all, delete-orphan")
    containers = relationship("Container", back_populates="tenant", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="tenant", cascade="all, delete-orphan")

    @validates('name')
    def validate_name(self, key, name):
        """Validate tenant name - must be DNS-safe"""
        if not name or len(name) < 3 or len(name) > 63:
            raise ValueError("Tenant name must be 3-63 characters")
        if not name.replace('-', '').replace('_', '').isalnum():
            raise ValueError("Tenant name must be alphanumeric with hyphens/underscores")
        return name.lower()

class User(Base):
    """User model with multi-tenant isolation"""
    __tablename__ = 'users'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False)
    username = Column(String(100), nullable=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    
    # Tenant association - CRITICAL for isolation
    tenant_id = Column(String(36), ForeignKey('tenants.id'), nullable=False)
    role = Column(String(50), nullable=False, default=RoleType.USER.value)
    
    # Account status
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Security settings
    mfa_enabled = Column(Boolean, default=False)
    mfa_secret = Column(String(32), nullable=True)
    api_key_hash = Column(String(255), nullable=True)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    quotas = relationship("UserQuota", back_populates="user", cascade="all, delete-orphan")
    containers = relationship("Container", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str):
        """Securely hash and store password"""
        if len(password) < 12:
            raise ValueError("Password must be at least 12 characters")
        salt = bcrypt.gensalt(rounds=12)
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def check_password(self, password: str) -> bool:
        """Verify password against stored hash"""
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    
    @validates('role')
    def validate_role(self, key, role):
        """Validate role is a valid RoleType"""
        if role not in [r.value for r in RoleType]:
            raise ValueError(f"Invalid role: {role}")
        return role
    
    @validates('email')
    def validate_email(self, key, email):
        """Basic email validation"""
        if not email or '@' not in email or len(email) > 255:
            raise ValueError("Invalid email address")
        return email.lower()

class Role(Base):
    """Role definitions with permissions"""
    __tablename__ = 'roles'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_system_role = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    permissions = relationship("Permission", back_populates="role", cascade="all, delete-orphan")

class Permission(Base):
    """Granular permissions for RBAC"""
    __tablename__ = 'permissions'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    role_id = Column(String(36), ForeignKey('roles.id'), nullable=False)
    resource = Column(String(100), nullable=False)  # containers, users, tenants, etc.
    action = Column(String(50), nullable=False)     # create, read, update, delete
    scope = Column(String(50), nullable=False)      # own, tenant, global
    
    # Relationships
    role = relationship("Role", back_populates="permissions")

class TenantQuota(Base):
    """Resource quotas per tenant"""
    __tablename__ = 'tenant_quotas'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey('tenants.id'), nullable=False)
    resource_type = Column(String(50), nullable=False)
    max_value = Column(Float, nullable=False)
    current_value = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    tenant = relationship("Tenant", back_populates="quotas")
    
    @validates('resource_type')
    def validate_resource_type(self, key, resource_type):
        """Validate resource type is valid"""
        if resource_type not in [r.value for r in ResourceType]:
            raise ValueError(f"Invalid resource type: {resource_type}")
        return resource_type

class UserQuota(Base):
    """Resource quotas per user"""
    __tablename__ = 'user_quotas'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    resource_type = Column(String(50), nullable=False)
    max_value = Column(Float, nullable=False)
    current_value = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", back_populates="quotas")
    
    @validates('resource_type')
    def validate_resource_type(self, key, resource_type):
        """Validate resource type is valid"""
        if resource_type not in [r.value for r in ResourceType]:
            raise ValueError(f"Invalid resource type: {resource_type}")
        return resource_type

class UserSession(Base):
    """User session tracking for security"""
    __tablename__ = 'user_sessions'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False)
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    user = relationship("User", back_populates="sessions")

class Container(Base):
    """Container instances with tenant/user isolation"""
    __tablename__ = 'containers'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    backend_type = Column(String(50), nullable=False)  # firecracker, lxc
    status = Column(String(50), nullable=False, default="created")
    
    # Ownership - CRITICAL for tenant isolation
    tenant_id = Column(String(36), ForeignKey('tenants.id'), nullable=False)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    
    # Resource allocation
    memory_mb = Column(Integer, nullable=False)
    cpu_count = Column(Integer, nullable=False)
    storage_gb = Column(Float, nullable=False)
    gpu_count = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    
    # Configuration
    template_name = Column(String(255), nullable=True)
    config_json = Column(Text, nullable=True)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="containers")
    user = relationship("User", back_populates="containers")

class AuditLog(Base):
    """Security audit logging"""
    __tablename__ = 'audit_logs'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey('tenants.id'), nullable=True)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=True)
    
    # Action details
    action = Column(String(100), nullable=False)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(36), nullable=True)
    
    # Context
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    details = Column(Text, nullable=True)  # JSON details
    
    # Severity and status
    severity = Column(String(20), nullable=False, default="info")  # info, warning, error, critical
    status = Column(String(20), nullable=False, default="success")  # success, failure, denied
    
    # Timestamp
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    tenant = relationship("Tenant", back_populates="audit_logs")
    user = relationship("User", back_populates="audit_logs")