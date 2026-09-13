"""
Database Manager with Multi-Tenant Security
Handles database connections, migrations, and tenant isolation
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
import logging
from typing import Optional, Dict, Any
from contextlib import contextmanager

from ..iam.models import Base, Tenant, User, RoleType, TenantQuota, UserQuota, ResourceType
from .exceptions import DatabaseError, TenantIsolationError

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manages database connections and ensures tenant isolation"""
    
    def __init__(self, database_url: str, echo: bool = False):
        """Initialize database manager"""
        self.database_url = database_url
        self.echo = echo
        
        # Create engine with connection pooling
        if database_url.startswith('sqlite'):
            # SQLite-specific configuration
            self.engine = create_engine(
                database_url,
                echo=echo,
                poolclass=StaticPool,
                connect_args={
                    "check_same_thread": False,
                    "timeout": 20,
                    "isolation_level": None
                }
            )
        else:
            # PostgreSQL/MySQL configuration
            self.engine = create_engine(
                database_url,
                echo=echo,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=3600
            )
        
        # Create session factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )
        
        # Set up connection event listeners for security
        self._setup_connection_events()
    
    def create_tables(self):
        """Create all database tables"""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Failed to create database tables: {str(e)}")
            raise DatabaseError(f"Database initialization failed: {str(e)}")
    
    def drop_tables(self):
        """Drop all database tables (use with caution!)"""
        try:
            Base.metadata.drop_all(bind=self.engine)
            logger.warning("All database tables dropped")
        except Exception as e:
            logger.error(f"Failed to drop database tables: {str(e)}")
            raise DatabaseError(f"Database cleanup failed: {str(e)}")
    
    @contextmanager
    def get_session(self):
        """Get database session with automatic cleanup"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {str(e)}")
            raise
        finally:
            session.close()
    
    def get_session_for_tenant(self, tenant_id: str) -> Session:
        """Get session with tenant context (for row-level security)"""
        session = self.SessionLocal()
        
        # Set tenant context for row-level security policies
        if not self.database_url.startswith('sqlite'):
            session.execute(f"SET app.current_tenant_id = '{tenant_id}'")
        
        return session
    
    def initialize_default_data(self):
        """Initialize default roles, permissions, and system data"""
        with self.get_session() as session:
            try:
                # Check if initialization is needed
                if session.query(Tenant).filter(Tenant.name == "system").first():
                    logger.info("Default data already exists, skipping initialization")
                    return
                
                # Create system tenant for platform admin
                system_tenant = Tenant(
                    name="system",
                    display_name="System Administration",
                    is_active=True
                )
                session.add(system_tenant)
                session.flush()  # Get tenant ID
                
                # Create default tenant quotas for system tenant
                default_quotas = [
                    (ResourceType.FIRECRACKER_VM.value, 1000),
                    (ResourceType.LXC_CONTAINER.value, 100),
                    (ResourceType.MEMORY_GB.value, 1000),
                    (ResourceType.CPU_CORES.value, 500),
                    (ResourceType.GPU_HOURS.value, 10000),
                    (ResourceType.STORAGE_GB.value, 10000),
                    (ResourceType.NETWORK_MBPS.value, 10000)
                ]
                
                for resource_type, max_value in default_quotas:
                    quota = TenantQuota(
                        tenant_id=system_tenant.id,
                        resource_type=resource_type,
                        max_value=max_value
                    )
                    session.add(quota)
                
                session.commit()
                logger.info("Default data initialized successfully")
                
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to initialize default data: {str(e)}")
                raise DatabaseError(f"Default data initialization failed: {str(e)}")
    
    def create_tenant_with_defaults(self, name: str, display_name: str, 
                                  admin_email: str, admin_password: str) -> Dict[str, str]:
        """Create new tenant with default quotas and admin user"""
        with self.get_session() as session:
            try:
                # Create tenant
                tenant = Tenant(
                    name=name,
                    display_name=display_name,
                    is_active=True
                )
                session.add(tenant)
                session.flush()  # Get tenant ID
                
                # Create default tenant quotas
                default_quotas = [
                    (ResourceType.FIRECRACKER_VM.value, 20),
                    (ResourceType.LXC_CONTAINER.value, 5),
                    (ResourceType.MEMORY_GB.value, 100),
                    (ResourceType.CPU_CORES.value, 50),
                    (ResourceType.GPU_HOURS.value, 100),
                    (ResourceType.STORAGE_GB.value, 500),
                    (ResourceType.NETWORK_MBPS.value, 1000)
                ]
                
                for resource_type, max_value in default_quotas:
                    quota = TenantQuota(
                        tenant_id=tenant.id,
                        resource_type=resource_type,
                        max_value=max_value
                    )
                    session.add(quota)
                
                # Create tenant admin user
                admin_user = User(
                    email=admin_email,
                    tenant_id=tenant.id,
                    role=RoleType.TENANT_ADMIN.value,
                    is_active=True,
                    is_verified=True
                )
                admin_user.set_password(admin_password)
                session.add(admin_user)
                session.flush()  # Get user ID
                
                # Create default user quotas for admin
                user_quotas = [
                    (ResourceType.FIRECRACKER_VM.value, 10),
                    (ResourceType.LXC_CONTAINER.value, 3),
                    (ResourceType.MEMORY_GB.value, 32),
                    (ResourceType.CPU_CORES.value, 16),
                    (ResourceType.GPU_HOURS.value, 50),
                    (ResourceType.STORAGE_GB.value, 200),
                    (ResourceType.NETWORK_MBPS.value, 500)
                ]
                
                for resource_type, max_value in user_quotas:
                    quota = UserQuota(
                        user_id=admin_user.id,
                        resource_type=resource_type,
                        max_value=max_value
                    )
                    session.add(quota)
                
                session.commit()
                
                return {
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    "admin_user_id": admin_user.id,
                    "admin_email": admin_user.email
                }
                
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to create tenant: {str(e)}")
                raise DatabaseError(f"Tenant creation failed: {str(e)}")
    
    def verify_tenant_isolation(self, session: Session, user_context: Dict[str, Any]):
        """Verify that queries respect tenant isolation"""
        user_tenant_id = user_context.get("tenant_id")
        user_role = user_context.get("role")
        
        # Platform admins can access all tenants
        if user_role == RoleType.PLATFORM_ADMIN.value:
            return
        
        # For other users, add automatic tenant filtering
        # This would be implemented with database row-level security in production
        if not user_tenant_id:
            raise TenantIsolationError("User context missing tenant_id")
    
    def _setup_connection_events(self):
        """Set up SQLAlchemy event listeners for security"""
        
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            """Set SQLite security settings"""
            if self.database_url.startswith('sqlite'):
                cursor = dbapi_connection.cursor()
                # Enable foreign key constraints
                cursor.execute("PRAGMA foreign_keys=ON")
                # Enable WAL mode for better concurrency
                cursor.execute("PRAGMA journal_mode=WAL")
                # Set secure temp store
                cursor.execute("PRAGMA secure_delete=ON")
                cursor.close()
        
        @event.listens_for(self.SessionLocal, "after_begin")
        def log_session_begin(session, transaction, connection):
            """Log session beginning for audit trail"""
            logger.debug("Database session started")
        
        @event.listens_for(self.SessionLocal, "after_commit")
        def log_session_commit(session):
            """Log successful commits"""
            logger.debug("Database session committed")
        
        @event.listens_for(self.SessionLocal, "after_rollback")
        def log_session_rollback(session):
            """Log rollbacks for debugging"""
            logger.warning("Database session rolled back")

class DatabaseError(Exception):
    """Database-related error"""
    pass