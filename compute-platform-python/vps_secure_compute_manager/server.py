"""
VPS Secure Compute Manager - Production Server
FastAPI-based REST API with authentication, authorization, and full container management
"""

import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, status, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import yaml

# Import our core components
from .core.database import DatabaseManager
from .core.template_manager import TemplateManager
from .core.container_orchestrator import ContainerOrchestrator, ServiceSpec, HealthCheck
from .core.network_manager import NetworkManager, NetworkType
from .core.storage_manager import StorageManager, VolumeType, VolumeConfig
from .core.resource_manager import ResourceManager
from .core.security_manager import SecurityManager
from .iam.auth import AuthenticationManager, AuthorizationManager
from .backends.firecracker import FirecrackerBackend
from .backends.lxc import LXCBackend
from .core.docker_converter import DockerConverter, BackendType
from .core.exceptions import *

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/vps-secure-compute/api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Request/Response Models
class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    tenant_id: str
    role: str

class ContainerCreateRequest(BaseModel):
    name: str
    template: str
    memory_mb: int = Field(ge=64, le=16384)
    cpu_count: int = Field(ge=1, le=16)
    storage_gb: float = Field(ge=0.1, le=1000)
    gpu_count: int = Field(ge=0, le=8)
    environment: Dict[str, str] = {}
    networks: List[str] = []
    volumes: List[str] = []

class ContainerResponse(BaseModel):
    id: str
    name: str
    status: str
    backend_type: str
    memory_mb: int
    cpu_count: int
    storage_gb: float
    gpu_count: int
    ip_address: Optional[str]
    created_at: str
    user_id: str
    tenant_id: str

class ServiceCreateRequest(BaseModel):
    name: str
    container_template: str
    replicas: int = Field(ge=1, le=100)
    memory_mb: int = Field(ge=64, le=16384)
    cpu_count: int = Field(ge=1, le=16)
    storage_gb: float = Field(ge=0.1, le=1000)
    environment: Dict[str, str] = {}
    health_check_command: Optional[List[str]] = None

class NetworkCreateRequest(BaseModel):
    name: str
    type: str
    subnet: str
    gateway: str
    isolated: bool = True
    internet_access: bool = False

class VolumeCreateRequest(BaseModel):
    name: str
    size_gb: float = Field(ge=0.1, le=1000)
    type: str = "encrypted"
    encrypted: bool = True

class DockerConversionRequest(BaseModel):
    image_name: str
    container_name: str
    backend_preference: str = "auto"  # auto, firecracker, lxc
    performance_requirements: Optional[Dict[str, Any]] = None
    user_overrides: Optional[Dict[str, Any]] = None

class DockerAnalysisRequest(BaseModel):
    image_name: str

class DockerComposeConversionRequest(BaseModel):
    compose_content: str
    project_name: str = "converted-project"

class DockerConversionResponse(BaseModel):
    container_id: str
    container_name: str
    selected_backend: str
    configuration: Dict[str, Any]
    recommendations: List[str]

class DockerAnalysisResponse(BaseModel):
    image_analysis: Dict[str, Any]
    backend_scores: Dict[str, int]
    recommended_backend: str
    requirements: Dict[str, Any]
    optimization_suggestions: List[str]

class DockerComposeConversionResponse(BaseModel):
    converted_services: Dict[str, Any]
    total_services: int
    backend_distribution: Dict[str, int]
    warnings: List[str]

# Global application state
class AppState:
    def __init__(self):
        self.config: Dict[str, Any] = {}
        self.db_manager: DatabaseManager = None
        self.auth_manager: AuthenticationManager = None
        self.authz_manager: AuthorizationManager = None
        self.template_manager: TemplateManager = None
        self.network_manager: NetworkManager = None
        self.storage_manager: StorageManager = None
        self.resource_manager: ResourceManager = None
        self.security_manager: SecurityManager = None
        self.firecracker_backend: FirecrackerBackend = None
        self.lxc_backend: LXCBackend = None
        self.orchestrator: ContainerOrchestrator = None
        self.docker_converter: DockerConverter = None

app_state = AppState()

# FastAPI app
app = FastAPI(
    title="VPS Secure Compute Manager",
    description="Secure multi-tenant container platform with Firecracker and LXC",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Import and mount dashboard
from .web.dashboard import dashboard, set_app_state
app.mount("/", dashboard)

# Security middleware
security = HTTPBearer()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://admin.vps-secure.com", "https://dashboard.vps-secure.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Trusted host middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["api.vps-secure.com", "localhost", "127.0.0.1"]
)

def load_config():
    """Load configuration from file"""
    config_path = os.getenv("VPS_CONFIG_PATH", "/etc/vps-secure-compute/config.yaml")
    
    if not os.path.exists(config_path):
        # Create default config
        default_config = {
            "database": {
                "url": "postgresql://vps_user:vps_pass@localhost:5432/vps_secure_compute"
            },
            "jwt": {
                "secret_key": os.urandom(32).hex(),
                "algorithm": "HS256",
                "expire_minutes": 60
            },
            "storage": {
                "path": "/opt/vps-secure-compute/storage",
                "backup_path": "/opt/vps-secure-compute/backups"
            },
            "templates": {
                "path": "/opt/vps-secure-compute/templates",
                "registry_url": "https://templates.vps-secure.com"
            },
            "firecracker": {
                "binary": "/usr/bin/firecracker",
                "kernel_path": "/opt/vps-secure-compute/kernels",
                "rootfs_path": "/opt/vps-secure-compute/rootfs"
            },
            "security": {
                "max_containers_per_user": 50,
                "max_memory_per_user_gb": 64,
                "max_cpu_per_user": 32,
                "audit_log_retention_days": 365
            }
        }
        
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False)
        
        logger.info(f"Created default config at {config_path}")
    
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Extract current user from JWT token"""
    try:
        token = credentials.credentials
        payload = app_state.auth_manager.verify_jwt_token(token)
        
        with app_state.db_manager.get_session() as session:
            from .iam.models import User
            user = session.query(User).filter(User.id == payload["user_id"]).first()
            
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid user"
                )
            
            return {
                "user_id": user.id,
                "tenant_id": user.tenant_id,
                "email": user.email,
                "role": user.role
            }
    
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    try:
        logger.info("🚀 Starting VPS Secure Compute Manager...")
        
        # Load configuration
        app_state.config = load_config()
        logger.info("✅ Configuration loaded")
        
        # Initialize database
        app_state.db_manager = DatabaseManager(app_state.config["database"]["url"])
        app_state.db_manager.create_tables()
        app_state.db_manager.initialize_default_data()
        logger.info("✅ Database initialized")
        
        # Initialize authentication
        app_state.auth_manager = AuthenticationManager(
            jwt_secret=app_state.config["jwt"]["secret_key"],
            jwt_algorithm=app_state.config["jwt"]["algorithm"]
        )
        app_state.authz_manager = AuthorizationManager()
        logger.info("✅ Authentication initialized")
        
        # Initialize infrastructure managers
        app_state.template_manager = TemplateManager(
            template_path=app_state.config["templates"]["path"],
            registry_url=app_state.config["templates"]["registry_url"]
        )
        
        app_state.network_manager = NetworkManager()
        
        app_state.storage_manager = StorageManager(
            storage_path=app_state.config["storage"]["path"],
            backup_path=app_state.config["storage"]["backup_path"]
        )
        
        app_state.resource_manager = ResourceManager()
        app_state.security_manager = SecurityManager()
        logger.info("✅ Infrastructure managers initialized")
        
        # Initialize container backends
        app_state.firecracker_backend = FirecrackerBackend(
            firecracker_binary=app_state.config["firecracker"]["binary"],
            kernel_path=app_state.config["firecracker"]["kernel_path"],
            rootfs_path=app_state.config["firecracker"]["rootfs_path"],
            template_manager=app_state.template_manager,
            network_manager=app_state.network_manager,
            storage_manager=app_state.storage_manager
        )
        
        app_state.lxc_backend = LXCBackend(
            template_manager=app_state.template_manager,
            network_manager=app_state.network_manager,
            storage_manager=app_state.storage_manager
        )
        logger.info("✅ Container backends initialized")
        
        # Initialize orchestrator
        app_state.orchestrator = ContainerOrchestrator(
            backend=app_state.firecracker_backend,  # Default to Firecracker
            resource_manager=app_state.resource_manager
        )
        logger.info("✅ Container orchestrator initialized")
        
        # Initialize Docker converter
        app_state.docker_converter = DockerConverter(app_state.config)
        logger.info("✅ Docker converter initialized")
        
        # Sync templates from registry
        await app_state.template_manager.sync_with_registry()
        logger.info("✅ Template registry synchronized")
        
        # Set app state for dashboard
        set_app_state(app_state)
        
        logger.info("🎉 VPS Secure Compute Manager started successfully!")
        
    except Exception as e:
        logger.error(f"❌ Failed to start application: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("🛑 Shutting down VPS Secure Compute Manager...")
    
    # Stop all containers gracefully
    if app_state.orchestrator:
        for service_name in list(app_state.orchestrator.services.keys()):
            await app_state.orchestrator.stop_service(service_name)
    
    logger.info("✅ VPS Secure Compute Manager shut down successfully")

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }

# Authentication endpoints
@app.post("/api/v1/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """User login"""
    try:
        with app_state.db_manager.get_session() as session:
            auth_result = app_state.auth_manager.authenticate_user(
                session, request.email, request.password
            )
            
            return LoginResponse(
                access_token=auth_result["jwt_token"],
                expires_in=3600,
                user_id=auth_result["user_id"],
                tenant_id=auth_result["tenant_id"],
                role=auth_result["role"]
            )
    
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )

@app.post("/api/v1/auth/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """User logout"""
    # In a real implementation, we'd invalidate the JWT token
    return {"message": "Logged out successfully"}

# Container management endpoints
@app.get("/api/v1/containers", response_model=List[ContainerResponse])
async def list_containers(current_user: dict = Depends(get_current_user)):
    """List user's containers"""
    try:
        # Get containers for user's tenant
        containers = await app_state.firecracker_backend.list_containers(
            tenant_id=current_user["tenant_id"]
        )
        
        return [
            ContainerResponse(
                id=container.id,
                name=container.name,
                status=container.status.value,
                backend_type=container.backend_type,
                memory_mb=container.memory_mb,
                cpu_count=container.cpu_count,
                storage_gb=container.storage_gb,
                gpu_count=container.gpu_count,
                ip_address=container.ip_address,
                created_at=container.created_at,
                user_id=container.user_id,
                tenant_id=container.tenant_id
            )
            for container in containers
        ]
        
    except Exception as e:
        logger.error(f"Failed to list containers: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list containers"
        )

@app.post("/api/v1/containers", response_model=ContainerResponse)
async def create_container(
    request: ContainerCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Create a new container"""
    try:
        from .backends.base import ContainerConfig
        
        # Check user permissions
        with app_state.db_manager.get_session() as session:
            # Check resource quotas
            quota_check = app_state.resource_manager.check_resource_availability(
                session,
                current_user["user_id"],
                {
                    "memory_mb": request.memory_mb,
                    "cpu_count": request.cpu_count,
                    "storage_gb": request.storage_gb
                }
            )
            
            if not quota_check["available"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient resources: {quota_check['reason']}"
                )
        
        # Create container configuration
        config = ContainerConfig(
            name=request.name,
            template=request.template,
            memory_mb=request.memory_mb,
            cpu_count=request.cpu_count,
            storage_gb=request.storage_gb,
            gpu_count=request.gpu_count,
            network_config={"networks": request.networks},
            security_config={},
            environment=request.environment,
            volumes=request.volumes,
            user_context=current_user
        )
        
        # Choose backend based on GPU requirements
        backend = app_state.lxc_backend if request.gpu_count > 0 else app_state.firecracker_backend
        
        # Create container
        container_id = await backend.create_container(config)
        
        # Get container info
        container_info = await backend.get_container_info(container_id)
        
        return ContainerResponse(
            id=container_info.id,
            name=container_info.name,
            status=container_info.status.value,
            backend_type=container_info.backend_type,
            memory_mb=container_info.memory_mb,
            cpu_count=container_info.cpu_count,
            storage_gb=container_info.storage_gb,
            gpu_count=container_info.gpu_count,
            ip_address=container_info.ip_address,
            created_at=container_info.created_at,
            user_id=container_info.user_id,
            tenant_id=container_info.tenant_id
        )
        
    except Exception as e:
        logger.error(f"Failed to create container: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create container: {str(e)}"
        )

@app.get("/api/v1/containers/{container_id}", response_model=ContainerResponse)
async def get_container(
    container_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get container details"""
    try:
        # Try both backends
        container_info = None
        try:
            container_info = await app_state.firecracker_backend.get_container_info(container_id)
        except:
            container_info = await app_state.lxc_backend.get_container_info(container_id)
        
        if not container_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Container not found"
            )
        
        # Check tenant isolation
        if container_info.tenant_id != current_user["tenant_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        return ContainerResponse(
            id=container_info.id,
            name=container_info.name,
            status=container_info.status.value,
            backend_type=container_info.backend_type,
            memory_mb=container_info.memory_mb,
            cpu_count=container_info.cpu_count,
            storage_gb=container_info.storage_gb,
            gpu_count=container_info.gpu_count,
            ip_address=container_info.ip_address,
            created_at=container_info.created_at,
            user_id=container_info.user_id,
            tenant_id=container_info.tenant_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get container {container_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get container"
        )

@app.post("/api/v1/containers/{container_id}/start")
async def start_container(
    container_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Start container"""
    try:
        # Get container info first to check ownership
        container_info = None
        backend = None
        
        try:
            container_info = await app_state.firecracker_backend.get_container_info(container_id)
            backend = app_state.firecracker_backend
        except:
            container_info = await app_state.lxc_backend.get_container_info(container_id)
            backend = app_state.lxc_backend
        
        if not container_info or container_info.tenant_id != current_user["tenant_id"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Container not found"
            )
        
        # Start container
        success = await backend.start_container(container_id)
        
        if success:
            return {"message": "Container started successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to start container"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start container {container_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start container"
        )

@app.post("/api/v1/containers/{container_id}/stop")
async def stop_container(
    container_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Stop container"""
    try:
        # Get container info first to check ownership
        container_info = None
        backend = None
        
        try:
            container_info = await app_state.firecracker_backend.get_container_info(container_id)
            backend = app_state.firecracker_backend
        except:
            container_info = await app_state.lxc_backend.get_container_info(container_id)
            backend = app_state.lxc_backend
        
        if not container_info or container_info.tenant_id != current_user["tenant_id"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Container not found"
            )
        
        # Stop container
        success = await backend.stop_container(container_id)
        
        if success:
            return {"message": "Container stopped successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to stop container"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop container {container_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stop container"
        )

@app.delete("/api/v1/containers/{container_id}")
async def delete_container(
    container_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete container"""
    try:
        # Get container info first to check ownership
        container_info = None
        backend = None
        
        try:
            container_info = await app_state.firecracker_backend.get_container_info(container_id)
            backend = app_state.firecracker_backend
        except:
            container_info = await app_state.lxc_backend.get_container_info(container_id)
            backend = app_state.lxc_backend
        
        if not container_info or container_info.tenant_id != current_user["tenant_id"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Container not found"
            )
        
        # Delete container
        success = await backend.destroy_container(container_id)
        
        if success:
            return {"message": "Container deleted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete container"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete container {container_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete container"
        )

# Template endpoints
@app.get("/api/v1/templates")
async def list_templates(current_user: dict = Depends(get_current_user)):
    """List available templates"""
    try:
        templates = app_state.template_manager.list_available_templates()
        
        return [
            {
                "name": template.name,
                "version": template.version,
                "architecture": template.architecture,
                "os_family": template.os_family,
                "os_version": template.os_version,
                "description": template.description,
                "size_mb": template.size_mb,
                "security_level": template.security_level,
                "features": template.features,
                "created_at": template.created_at.isoformat() if template.created_at else None
            }
            for template in templates
        ]
        
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list templates"
        )

# Volume endpoints
@app.get("/api/v1/volumes")
async def list_volumes(current_user: dict = Depends(get_current_user)):
    """List user's volumes"""
    try:
        volumes = app_state.storage_manager.list_volumes(tenant_id=current_user["tenant_id"])
        return volumes
        
    except Exception as e:
        logger.error(f"Failed to list volumes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list volumes"
        )

@app.post("/api/v1/volumes")
async def create_volume(
    request: VolumeCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Create a new volume"""
    try:
        config = VolumeConfig(
            name=request.name,
            size_gb=request.size_gb,
            type=VolumeType(request.type),
            tenant_id=current_user["tenant_id"],
            user_id=current_user["user_id"],
            encrypted=request.encrypted
        )
        
        volume_id = await app_state.storage_manager.create_volume(config)
        
        if volume_id:
            volume_info = app_state.storage_manager.get_volume_info(volume_id)
            return volume_info
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create volume"
            )
        
    except Exception as e:
        logger.error(f"Failed to create volume: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create volume: {str(e)}"
        )

# Network endpoints
@app.get("/api/v1/networks")
async def list_networks(current_user: dict = Depends(get_current_user)):
    """List user's networks"""
    try:
        networks = app_state.network_manager.list_networks(tenant_id=current_user["tenant_id"])
        return networks
        
    except Exception as e:
        logger.error(f"Failed to list networks: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list networks"
        )

@app.post("/api/v1/networks")
async def create_network(
    request: NetworkCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Create a new network"""
    try:
        success = await app_state.network_manager.create_network(
            name=request.name,
            network_type=NetworkType(request.type),
            subnet=request.subnet,
            gateway=request.gateway,
            tenant_id=current_user["tenant_id"],
            isolated=request.isolated,
            internet_access=request.internet_access
        )
        
        if success:
            return {"message": "Network created successfully", "name": request.name}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create network"
            )
        
    except Exception as e:
        logger.error(f"Failed to create network: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create network: {str(e)}"
        )

# Service orchestration endpoints
@app.get("/api/v1/services")
async def list_services(current_user: dict = Depends(get_current_user)):
    """List user's services"""
    try:
        services = app_state.orchestrator.list_services()
        
        # Filter by tenant
        user_services = []
        for service in services:
            # Check if any instances belong to this tenant
            for instance in service.get("instances", []):
                # This would need tenant filtering logic
                pass
        
        return services
        
    except Exception as e:
        logger.error(f"Failed to list services: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list services"
        )

# Docker conversion endpoints
@app.post("/api/v1/docker/analyze", response_model=DockerAnalysisResponse)
async def analyze_docker_image(
    request: DockerAnalysisRequest,
    current_user: dict = Depends(get_current_user)
):
    """Analyze Docker image and get conversion recommendations"""
    try:
        logger.info(f"Analyzing Docker image: {request.image_name}")
        
        # Get recommendations from converter
        recommendations = await app_state.docker_converter.get_conversion_recommendations(
            request.image_name
        )
        
        return DockerAnalysisResponse(
            image_analysis=recommendations["image_analysis"],
            backend_scores=recommendations["backend_scores"],
            recommended_backend=recommendations["recommended_backend"],
            requirements=recommendations["requirements"],
            optimization_suggestions=recommendations["optimization_suggestions"]
        )
        
    except ConversionError as e:
        logger.error(f"Docker image analysis failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image analysis failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to analyze Docker image: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to analyze Docker image"
        )

@app.post("/api/v1/docker/convert", response_model=DockerConversionResponse)
async def convert_docker_container(
    request: DockerConversionRequest,
    current_user: dict = Depends(get_current_user)
):
    """Convert Docker container to native container format and create it"""
    try:
        logger.info(f"Converting Docker container: {request.image_name} -> {request.container_name}")
        
        # Validate backend preference
        backend_preference = BackendType.AUTO
        if request.backend_preference.lower() == "firecracker":
            backend_preference = BackendType.FIRECRACKER
        elif request.backend_preference.lower() == "lxc":
            backend_preference = BackendType.LXC
        
        # Perform conversion and create container
        container_id = await app_state.docker_converter.create_converted_container(
            image_name=request.image_name,
            container_name=request.container_name,
            backend_preference=backend_preference,
            performance_requirements=request.performance_requirements,
            user_overrides=request.user_overrides
        )
        
        # Get the created container info
        container_info = None
        backend_type = None
        try:
            container_info = await app_state.firecracker_backend.get_container_info(container_id)
            backend_type = "firecracker"
        except:
            container_info = await app_state.lxc_backend.get_container_info(container_id)
            backend_type = "lxc"
        
        # Get recommendations for optimization
        recommendations_data = await app_state.docker_converter.get_conversion_recommendations(
            request.image_name
        )
        
        return DockerConversionResponse(
            container_id=container_id,
            container_name=request.container_name,
            selected_backend=backend_type,
            configuration={
                "memory_mb": container_info.memory_mb,
                "cpu_count": container_info.cpu_count,
                "storage_gb": container_info.storage_gb,
                "gpu_enabled": container_info.gpu_count > 0,
                "backend_type": backend_type
            },
            recommendations=recommendations_data["optimization_suggestions"]
        )
        
    except ConversionError as e:
        logger.error(f"Docker conversion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Conversion failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to convert Docker container: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to convert Docker container"
        )

@app.post("/api/v1/docker/compose/convert", response_model=DockerComposeConversionResponse)
async def convert_docker_compose(
    request: DockerComposeConversionRequest,
    current_user: dict = Depends(get_current_user)
):
    """Convert Docker Compose file to native containers"""
    try:
        logger.info(f"Converting Docker Compose project: {request.project_name}")
        
        # Write compose content to temporary file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write(request.compose_content)
            compose_file_path = f.name
        
        try:
            # Convert compose file
            converted_services = await app_state.docker_converter.batch_convert_compose_file(
                compose_file_path
            )
            
            # Count backend distribution
            backend_distribution = {"firecracker": 0, "lxc": 0}
            warnings = []
            
            for service_name, (config, backend) in converted_services.items():
                backend_distribution[backend.value] += 1
                
                # Add warnings for potential issues
                if config.gpu_enabled and backend == BackendType.FIRECRACKER:
                    warnings.append(f"Service {service_name}: GPU requested but Firecracker selected")
                if config.privileged and backend == BackendType.FIRECRACKER:
                    warnings.append(f"Service {service_name}: Privileged access requested but Firecracker selected")
            
            # Prepare response data
            converted_services_data = {}
            for service_name, (config, backend) in converted_services.items():
                converted_services_data[service_name] = {
                    "backend": backend.value,
                    "configuration": {
                        "memory_mb": config.memory_mb,
                        "cpu_count": config.cpu_count,
                        "storage_gb": config.storage_gb,
                        "gpu_enabled": config.gpu_enabled,
                        "privileged": config.privileged
                    }
                }
            
            return DockerComposeConversionResponse(
                converted_services=converted_services_data,
                total_services=len(converted_services),
                backend_distribution=backend_distribution,
                warnings=warnings
            )
            
        finally:
            # Clean up temporary file
            import os
            try:
                os.unlink(compose_file_path)
            except:
                pass
        
    except ConversionError as e:
        logger.error(f"Docker Compose conversion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Compose conversion failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to convert Docker Compose: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to convert Docker Compose"
        )

@app.get("/api/v1/docker/backends")
async def get_available_backends(current_user: dict = Depends(get_current_user)):
    """Get available conversion backends and their capabilities"""
    try:
        return {
            "backends": {
                "firecracker": {
                    "name": "Firecracker MicroVMs",
                    "description": "Ultra-fast boot times (<150ms) with KVM isolation",
                    "best_for": [
                        "Microservices",
                        "Serverless functions", 
                        "High isolation requirements",
                        "Fast startup times",
                        "Small to medium workloads"
                    ],
                    "limitations": [
                        "No GPU support",
                        "No privileged operations",
                        "Limited to 8GB RAM per VM",
                        "No systemd support"
                    ],
                    "available": True
                },
                "lxc": {
                    "name": "Hardened LXC Containers",
                    "description": "Full system containers with GPU support and AppArmor profiles",
                    "best_for": [
                        "GPU workloads",
                        "Large applications",
                        "System services",
                        "Legacy applications",
                        "High performance computing"
                    ],
                    "limitations": [
                        "Slower startup than Firecracker",
                        "Shared kernel with host",
                        "More resource overhead"
                    ],
                    "available": True
                }
            },
            "selection_criteria": {
                "auto_selection_factors": [
                    "GPU requirements",
                    "Memory and CPU requirements", 
                    "Privileged access needs",
                    "Startup time requirements",
                    "Application type and complexity"
                ],
                "force_lxc_conditions": [
                    "GPU/CUDA required",
                    "Privileged access required",
                    "SystemD services",
                    "Large resource requirements (>8GB RAM)"
                ],
                "prefer_firecracker_conditions": [
                    "Fast startup required (<500ms)",
                    "Microservice architecture",
                    "High isolation requirements",
                    "Small resource footprint"
                ]
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get backend information: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get backend information"
        )

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "timestamp": datetime.now(timezone.utc).isoformat()}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "timestamp": datetime.now(timezone.utc).isoformat()}
    )

def main():
    """Main entry point"""
    config = load_config()
    
    uvicorn.run(
        "vps_secure_compute_manager.server:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        workers=1,
        log_level="info",
        access_log=True,
        server_header=False,
        date_header=False
    )

if __name__ == "__main__":
    main()