"""
Container Orchestration System for VPS Secure Compute Manager
Handles container lifecycle, health monitoring, scaling, and service discovery
"""

import asyncio
import logging
import time
import json
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
import uuid

from ..backends.base import ContainerStatus, ContainerInfo
from ..core.exceptions import ContainerError
from .resource_manager import ResourceManager

logger = logging.getLogger(__name__)

class HealthStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    DEGRADED = "degraded"

class ServiceStatus(Enum):
    RUNNING = "running"
    STARTING = "starting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    SCALING = "scaling"

@dataclass
class HealthCheck:
    """Container health check configuration"""
    command: List[str]
    interval_seconds: int = 30
    timeout_seconds: int = 10
    retries: int = 3
    start_period_seconds: int = 60

@dataclass
class ServiceSpec:
    """Service specification for orchestration"""
    name: str
    container_template: str
    replicas: int = 1
    min_replicas: int = 1
    max_replicas: int = 10
    resource_requirements: Dict[str, Any] = None
    health_check: HealthCheck = None
    environment: Dict[str, str] = None
    networks: List[str] = None
    volumes: List[str] = None
    labels: Dict[str, str] = None
    restart_policy: str = "always"  # "always", "on-failure", "never"
    update_strategy: str = "rolling"  # "rolling", "recreate"

@dataclass
class ContainerInstance:
    """Container instance in a service"""
    id: str
    service_name: str
    container_id: str
    status: ContainerStatus
    health_status: HealthStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    last_health_check: Optional[datetime] = None
    restart_count: int = 0
    node_id: str = "local"

class ContainerOrchestrator:
    """Commercial-grade container orchestration system"""
    
    def __init__(self, backend, resource_manager: ResourceManager):
        self.backend = backend
        self.resource_manager = resource_manager
        
        # Service registry
        self.services: Dict[str, ServiceSpec] = {}
        self.instances: Dict[str, ContainerInstance] = {}
        
        # Monitoring
        self.health_checks_running = False
        self.scaling_decisions: Dict[str, float] = {}  # service -> last scaling decision time
        
        # Event system
        self.event_handlers: Dict[str, List[Callable]] = {
            "container_started": [],
            "container_stopped": [],
            "container_failed": [],
            "service_scaled": [],
            "health_check_failed": []
        }
    
    async def deploy_service(self, service_spec: ServiceSpec, user_context: Dict[str, Any]) -> bool:
        """Deploy a new service"""
        try:
            logger.info(f"Deploying service {service_spec.name} with {service_spec.replicas} replicas")
            
            # Validate resources
            if not await self._validate_service_resources(service_spec, user_context):
                raise ContainerError("Insufficient resources for service deployment")
            
            # Store service spec
            self.services[service_spec.name] = service_spec
            
            # Create initial replicas
            for i in range(service_spec.replicas):
                await self._create_service_instance(service_spec, user_context, replica_index=i)
            
            # Start health monitoring for this service
            asyncio.create_task(self._monitor_service_health(service_spec.name))
            
            await self._emit_event("service_deployed", {"service": service_spec.name, "replicas": service_spec.replicas})
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to deploy service {service_spec.name}: {e}")
            # Cleanup any partially created instances
            await self._cleanup_failed_service(service_spec.name)
            return False
    
    async def _create_service_instance(self, service_spec: ServiceSpec, user_context: Dict[str, Any], replica_index: int = 0) -> str:
        """Create a single service instance"""
        from ..backends.base import ContainerConfig
        
        instance_id = str(uuid.uuid4())
        container_name = f"{service_spec.name}-{replica_index}-{instance_id[:8]}"
        
        # Prepare container configuration
        config = ContainerConfig(
            name=container_name,
            template=service_spec.container_template,
            memory_mb=service_spec.resource_requirements.get("memory_mb", 512),
            cpu_count=service_spec.resource_requirements.get("cpu_count", 1),
            storage_gb=service_spec.resource_requirements.get("storage_gb", 5.0),
            gpu_count=service_spec.resource_requirements.get("gpu_count", 0),
            network_config={"networks": service_spec.networks or []},
            security_config={},
            environment=service_spec.environment or {},
            volumes=service_spec.volumes or [],
            user_context=user_context
        )
        
        # Create container
        container_id = await self.backend.create_container(config)
        
        # Create instance record
        instance = ContainerInstance(
            id=instance_id,
            service_name=service_spec.name,
            container_id=container_id,
            status=ContainerStatus.CREATED,
            health_status=HealthStatus.UNKNOWN,
            created_at=datetime.now(timezone.utc)
        )
        
        self.instances[instance_id] = instance
        
        # Start container
        await self.backend.start_container(container_id)
        instance.status = ContainerStatus.RUNNING
        instance.started_at = datetime.now(timezone.utc)
        
        await self._emit_event("container_started", {"instance_id": instance_id, "container_id": container_id})
        
        return instance_id
    
    async def scale_service(self, service_name: str, new_replica_count: int, user_context: Dict[str, Any]) -> bool:
        """Scale service to specified replica count"""
        try:
            if service_name not in self.services:
                raise ContainerError(f"Service {service_name} not found")
            
            service_spec = self.services[service_name]
            current_instances = [inst for inst in self.instances.values() if inst.service_name == service_name]
            current_count = len(current_instances)
            
            # Validate scaling limits
            if new_replica_count < service_spec.min_replicas:
                new_replica_count = service_spec.min_replicas
            elif new_replica_count > service_spec.max_replicas:
                new_replica_count = service_spec.max_replicas
            
            if new_replica_count == current_count:
                logger.info(f"Service {service_name} already at desired replica count {new_replica_count}")
                return True
            
            logger.info(f"Scaling service {service_name} from {current_count} to {new_replica_count} replicas")
            
            if new_replica_count > current_count:
                # Scale up
                for i in range(new_replica_count - current_count):
                    await self._create_service_instance(service_spec, user_context, replica_index=current_count + i)
            else:
                # Scale down
                instances_to_remove = current_instances[new_replica_count:]
                for instance in instances_to_remove:
                    await self._remove_service_instance(instance.id)
            
            # Update service spec
            service_spec.replicas = new_replica_count
            
            await self._emit_event("service_scaled", {
                "service": service_name, 
                "old_count": current_count, 
                "new_count": new_replica_count
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to scale service {service_name}: {e}")
            return False
    
    async def _remove_service_instance(self, instance_id: str):
        """Remove a service instance"""
        if instance_id not in self.instances:
            return
        
        instance = self.instances[instance_id]
        
        try:
            # Stop and destroy container
            await self.backend.stop_container(instance.container_id)
            await self.backend.destroy_container(instance.container_id)
            
            # Remove from registry
            del self.instances[instance_id]
            
            await self._emit_event("container_stopped", {"instance_id": instance_id, "container_id": instance.container_id})
            
        except Exception as e:
            logger.error(f"Failed to remove instance {instance_id}: {e}")
    
    async def _monitor_service_health(self, service_name: str):
        """Monitor health of all instances in a service"""
        while service_name in self.services:
            try:
                service_spec = self.services[service_name]
                instances = [inst for inst in self.instances.values() if inst.service_name == service_name]
                
                for instance in instances:
                    await self._check_instance_health(instance, service_spec.health_check)
                
                # Check if we need to scale or restart instances
                await self._handle_unhealthy_instances(service_name)
                
                # Wait before next health check cycle
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"Error in health monitoring for service {service_name}: {e}")
                await asyncio.sleep(60)  # Wait longer on error
    
    async def _check_instance_health(self, instance: ContainerInstance, health_check: HealthCheck):
        """Check health of a single instance"""
        if not health_check:
            instance.health_status = HealthStatus.UNKNOWN
            return
        
        try:
            # Execute health check command
            result = await self.backend.exec_command(
                instance.container_id, 
                health_check.command,
                timeout=health_check.timeout_seconds
            )
            
            if result.exit_code == 0:
                instance.health_status = HealthStatus.HEALTHY
            else:
                instance.health_status = HealthStatus.UNHEALTHY
                await self._emit_event("health_check_failed", {
                    "instance_id": instance.id,
                    "container_id": instance.container_id,
                    "exit_code": result.exit_code
                })
            
            instance.last_health_check = datetime.now(timezone.utc)
            
        except Exception as e:
            logger.error(f"Health check failed for instance {instance.id}: {e}")
            instance.health_status = HealthStatus.UNHEALTHY
    
    async def _handle_unhealthy_instances(self, service_name: str):
        """Handle unhealthy instances by restarting or replacing them"""
        service_spec = self.services[service_name]
        instances = [inst for inst in self.instances.values() if inst.service_name == service_name]
        
        for instance in instances:
            if instance.health_status == HealthStatus.UNHEALTHY:
                if service_spec.restart_policy == "always" or service_spec.restart_policy == "on-failure":
                    await self._restart_instance(instance)
    
    async def _restart_instance(self, instance: ContainerInstance):
        """Restart an unhealthy instance"""
        try:
            logger.info(f"Restarting unhealthy instance {instance.id}")
            
            # Stop container
            await self.backend.stop_container(instance.container_id)
            
            # Start container
            await self.backend.start_container(instance.container_id)
            
            instance.restart_count += 1
            instance.started_at = datetime.now(timezone.utc)
            instance.health_status = HealthStatus.UNKNOWN
            
            await self._emit_event("container_restarted", {
                "instance_id": instance.id,
                "restart_count": instance.restart_count
            })
            
        except Exception as e:
            logger.error(f"Failed to restart instance {instance.id}: {e}")
            instance.status = ContainerStatus.FAILED
            await self._emit_event("container_failed", {"instance_id": instance.id})
    
    async def _validate_service_resources(self, service_spec: ServiceSpec, user_context: Dict[str, Any]) -> bool:
        """Validate that user has sufficient resources for service"""
        # Calculate total resource requirements
        total_memory = service_spec.resource_requirements.get("memory_mb", 512) * service_spec.replicas
        total_cpu = service_spec.resource_requirements.get("cpu_count", 1) * service_spec.replicas
        total_storage = service_spec.resource_requirements.get("storage_gb", 5.0) * service_spec.replicas
        
        # Check quotas (this would integrate with ResourceManager)
        # For now, we'll do a simple check
        return total_memory <= 16384 and total_cpu <= 32 and total_storage <= 1000
    
    async def _cleanup_failed_service(self, service_name: str):
        """Clean up instances of a failed service deployment"""
        instances_to_remove = [
            inst.id for inst in self.instances.values() 
            if inst.service_name == service_name
        ]
        
        for instance_id in instances_to_remove:
            await self._remove_service_instance(instance_id)
        
        if service_name in self.services:
            del self.services[service_name]
    
    def get_service_status(self, service_name: str) -> Dict[str, Any]:
        """Get current status of a service"""
        if service_name not in self.services:
            return {"error": "Service not found"}
        
        service_spec = self.services[service_name]
        instances = [inst for inst in self.instances.values() if inst.service_name == service_name]
        
        healthy_count = len([inst for inst in instances if inst.health_status == HealthStatus.HEALTHY])
        running_count = len([inst for inst in instances if inst.status == ContainerStatus.RUNNING])
        
        return {
            "name": service_name,
            "desired_replicas": service_spec.replicas,
            "current_replicas": len(instances),
            "running_replicas": running_count,
            "healthy_replicas": healthy_count,
            "instances": [
                {
                    "id": inst.id,
                    "container_id": inst.container_id,
                    "status": inst.status.value,
                    "health_status": inst.health_status.value,
                    "restart_count": inst.restart_count,
                    "created_at": inst.created_at.isoformat(),
                    "started_at": inst.started_at.isoformat() if inst.started_at else None
                }
                for inst in instances
            ]
        }
    
    def list_services(self) -> List[Dict[str, Any]]:
        """List all services"""
        return [self.get_service_status(name) for name in self.services.keys()]
    
    async def stop_service(self, service_name: str) -> bool:
        """Stop a service and all its instances"""
        if service_name not in self.services:
            return False
        
        instances = [inst for inst in self.instances.values() if inst.service_name == service_name]
        
        for instance in instances:
            await self._remove_service_instance(instance.id)
        
        del self.services[service_name]
        return True
    
    def add_event_handler(self, event_type: str, handler: Callable):
        """Add event handler for orchestration events"""
        if event_type in self.event_handlers:
            self.event_handlers[event_type].append(handler)
    
    async def _emit_event(self, event_type: str, data: Dict[str, Any]):
        """Emit orchestration event"""
        if event_type in self.event_handlers:
            for handler in self.event_handlers[event_type]:
                try:
                    await handler(event_type, data)
                except Exception as e:
                    logger.error(f"Event handler failed for {event_type}: {e}")
    
    async def auto_scale_services(self, metrics: Dict[str, Dict[str, float]]):
        """Auto-scale services based on metrics"""
        current_time = time.time()
        
        for service_name, service_metrics in metrics.items():
            if service_name not in self.services:
                continue
            
            # Rate limit scaling decisions (minimum 5 minutes between scaling)
            last_scaling = self.scaling_decisions.get(service_name, 0)
            if current_time - last_scaling < 300:
                continue
            
            service_spec = self.services[service_name]
            current_replicas = len([inst for inst in self.instances.values() if inst.service_name == service_name])
            
            # Simple scaling logic based on CPU and memory usage
            cpu_usage = service_metrics.get("cpu_usage_percent", 0)
            memory_usage = service_metrics.get("memory_usage_percent", 0)
            
            new_replicas = current_replicas
            
            # Scale up if high usage
            if cpu_usage > 80 or memory_usage > 85:
                new_replicas = min(current_replicas + 1, service_spec.max_replicas)
            
            # Scale down if low usage
            elif cpu_usage < 20 and memory_usage < 30:
                new_replicas = max(current_replicas - 1, service_spec.min_replicas)
            
            if new_replicas != current_replicas:
                logger.info(f"Auto-scaling {service_name}: {current_replicas} -> {new_replicas} (CPU: {cpu_usage}%, Mem: {memory_usage}%)")
                # This would need user_context, so we'd need to store it or get it from the service
                # await self.scale_service(service_name, new_replicas, user_context)
                self.scaling_decisions[service_name] = current_time