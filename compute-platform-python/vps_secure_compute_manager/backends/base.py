"""
Base Container Backend Interface
Defines common interface for Firecracker and LXC backends
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

class ContainerStatus(Enum):
    """Container status states"""
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    DESTROYED = "destroyed"

@dataclass
class ContainerInfo:
    """Container information"""
    id: str
    name: str
    status: ContainerStatus
    backend_type: str
    memory_mb: int
    cpu_count: int
    storage_gb: float
    gpu_count: int
    ip_address: Optional[str]
    created_at: str
    started_at: Optional[str]
    stopped_at: Optional[str]
    user_id: str
    tenant_id: str

@dataclass
class ContainerConfig:
    """Container configuration"""
    name: str
    template: str
    memory_mb: int
    cpu_count: int
    storage_gb: float
    gpu_count: int
    network_config: Dict[str, Any]
    security_config: Dict[str, Any]
    environment: Dict[str, str]
    volumes: List[Dict[str, str]]
    user_context: Dict[str, Any]

@dataclass
class ExecResult:
    """Command execution result"""
    exit_code: int
    stdout: str
    stderr: str
    execution_time: float

class ContainerBackend(ABC):
    """Abstract base class for container backends"""
    
    @abstractmethod
    async def create_container(self, config: ContainerConfig) -> str:
        """Create a new container"""
        pass
    
    @abstractmethod
    async def start_container(self, container_id: str) -> bool:
        """Start a container"""
        pass
    
    @abstractmethod
    async def stop_container(self, container_id: str, force: bool = False) -> bool:
        """Stop a container"""
        pass
    
    @abstractmethod
    async def destroy_container(self, container_id: str) -> bool:
        """Destroy a container"""
        pass
    
    @abstractmethod
    async def get_container_info(self, container_id: str) -> ContainerInfo:
        """Get container information"""
        pass
    
    @abstractmethod
    async def list_containers(self, tenant_id: str = None, user_id: str = None) -> List[ContainerInfo]:
        """List containers with optional filtering"""
        pass
    
    @abstractmethod
    async def exec_command(self, container_id: str, command: List[str], 
                          timeout: int = 30) -> ExecResult:
        """Execute command in container"""
        pass
    
    @abstractmethod
    async def get_logs(self, container_id: str, lines: int = 100) -> str:
        """Get container logs"""
        pass
    
    @abstractmethod
    async def get_metrics(self, container_id: str) -> Dict[str, Any]:
        """Get container resource metrics"""
        pass
    
    @abstractmethod
    def validate_config(self, config: ContainerConfig) -> bool:
        """Validate container configuration"""
        pass
    
    @abstractmethod
    def get_supported_templates(self) -> List[Dict[str, str]]:
        """Get list of supported templates"""
        pass