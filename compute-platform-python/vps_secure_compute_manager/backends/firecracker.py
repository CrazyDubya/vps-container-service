"""
Firecracker Backend Implementation
Manages Firecracker microVMs with security hardening
"""

import json
import asyncio
import aiohttp
import aiofiles
import tempfile
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
import uuid
import time
import subprocess
import os
import signal

from .base import ContainerBackend, ContainerConfig, ContainerInfo, ContainerStatus, ExecResult
from ..core.exceptions import FirecrackerError, SecurityViolation, ConfigurationError
from ..core.security_manager import SecurityManager
from ..core.template_manager import TemplateManager
from ..core.network_manager import NetworkManager, NetworkType
from ..core.storage_manager import StorageManager, VolumeConfig, VolumeType

logger = logging.getLogger(__name__)

class FirecrackerBackend(ContainerBackend):
    """Firecracker microVM backend with security hardening"""
    
    def __init__(self, firecracker_binary: str = "/usr/bin/firecracker",
                 kernel_path: str = "/opt/firecracker/kernels",
                 rootfs_path: str = "/opt/firecracker/rootfs",
                 runtime_path: str = "/var/run/vps-secure-compute",
                 template_manager: TemplateManager = None,
                 network_manager: NetworkManager = None,
                 storage_manager: StorageManager = None):
        
        self.firecracker_binary = firecracker_binary
        self.kernel_path = Path(kernel_path)
        self.rootfs_path = Path(rootfs_path)
        self.runtime_path = Path(runtime_path)
        self.security_manager = SecurityManager()
        
        # Infrastructure managers (with backward compatibility)
        self.template_manager = template_manager or TemplateManager()
        self.network_manager = network_manager or NetworkManager()
        self.storage_manager = storage_manager or StorageManager()
        
        # Container registry
        self.containers = {}
        self.processes = {}
        
        # Ensure runtime directory exists
        self.runtime_path.mkdir(parents=True, exist_ok=True)
        
        # Verify Firecracker binary exists
        if not Path(self.firecracker_binary).exists():
            raise ConfigurationError(f"Firecracker binary not found: {self.firecracker_binary}")
    
    async def create_container(self, config: ContainerConfig) -> str:
        """Create a new Firecracker microVM"""
        try:
            # Generate unique container ID
            container_id = str(uuid.uuid4())
            
            # Validate configuration
            if not await self.validate_config(config):
                raise FirecrackerError("Invalid container configuration")
            
            # Apply security hardening to configuration
            secured_config = self.security_manager.validate_container_config(
                "firecracker", config.__dict__, config.user_context
            )
            
            # Create container runtime directory
            container_dir = self.runtime_path / container_id
            container_dir.mkdir(parents=True, exist_ok=True)
            
            # Setup networking via NetworkManager
            network_name = config.network_config.get("network", "default") if config.network_config else "default"
            ip_address = await self.network_manager.attach_container_to_network(
                container_id, network_name
            )
            
            # Setup storage volumes via StorageManager
            volume_ids = []
            if config.storage_gb > 0:
                volume_config = VolumeConfig(
                    name=f"{container_id}-rootfs",
                    size_gb=config.storage_gb,
                    type=VolumeType.BLOCK,
                    tenant_id=config.user_context["tenant_id"],
                    user_id=config.user_context["user_id"]
                )
                volume_id = await self.storage_manager.create_volume(volume_config)
                if volume_id:
                    volume_ids.append(volume_id)
            
            # Prepare Firecracker configuration
            fc_config = await self._prepare_firecracker_config(
                container_id, config, secured_config, ip_address, volume_ids
            )
            
            # Write configuration file
            config_file = container_dir / "config.json"
            async with aiofiles.open(config_file, 'w') as f:
                await f.write(json.dumps(fc_config, indent=2))
            
            # Create container metadata
            container_info = ContainerInfo(
                id=container_id,
                name=config.name,
                status=ContainerStatus.CREATED,
                backend_type="firecracker",
                memory_mb=config.memory_mb,
                cpu_count=config.cpu_count,
                storage_gb=config.storage_gb,
                gpu_count=0,  # Firecracker doesn't support GPU
                ip_address=ip_address,
                created_at=time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                started_at=None,
                stopped_at=None,
                user_id=config.user_context["user_id"],
                tenant_id=config.user_context["tenant_id"]
            )
            
            # Store volume associations
            container_info.volume_ids = volume_ids
            
            # Store container info
            self.containers[container_id] = container_info
            
            # Start security monitoring
            self.security_manager.monitor_container_security(container_id, config.user_context)
            
            logger.info(f"Created Firecracker container {container_id} for user {config.user_context['user_id']}")
            return container_id
            
        except Exception as e:
            logger.error(f"Failed to create Firecracker container: {str(e)}")
            raise FirecrackerError(f"Container creation failed: {str(e)}")
    
    async def start_container(self, container_id: str) -> bool:
        """Start a Firecracker microVM"""
        try:
            if container_id not in self.containers:
                raise FirecrackerError(f"Container {container_id} not found")
            
            container_info = self.containers[container_id]
            
            if container_info.status != ContainerStatus.CREATED:
                raise FirecrackerError(f"Container {container_id} is not in created state")
            
            # Update status
            container_info.status = ContainerStatus.STARTING
            
            # Get configuration
            container_dir = self.runtime_path / container_id
            config_file = container_dir / "config.json"
            
            # Create socket paths
            api_socket = container_dir / "api.socket"
            metrics_socket = container_dir / "metrics.socket"
            
            # Start Firecracker process
            cmd = [
                self.firecracker_binary,
                "--api-sock", str(api_socket),
                "--metrics-path", str(metrics_socket),
                "--config-file", str(config_file),
                "--level", "Debug",  # Use Debug for security monitoring
                "--show-level",
                "--show-log-origin"
            ]
            
            # Set up process with security restrictions
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=container_dir,
                preexec_fn=self._setup_process_security
            )
            
            # Store process reference
            self.processes[container_id] = {
                "process": process,
                "api_socket": api_socket,
                "metrics_socket": metrics_socket,
                "pid": process.pid
            }
            
            # Wait for API socket to be ready
            await self._wait_for_api_socket(api_socket)
            
            # Configure and start the microVM via API
            await self._configure_microvm_via_api(container_id, api_socket)
            
            # Update container status
            container_info.status = ContainerStatus.RUNNING
            container_info.started_at = time.strftime("%Y-%m-%d %H:%M:%S UTC")
            
            logger.info(f"Started Firecracker container {container_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Firecracker container {container_id}: {str(e)}")
            if container_id in self.containers:
                self.containers[container_id].status = ContainerStatus.FAILED
            raise FirecrackerError(f"Container start failed: {str(e)}")
    
    async def stop_container(self, container_id: str, force: bool = False) -> bool:
        """Stop a Firecracker microVM"""
        try:
            if container_id not in self.containers:
                raise FirecrackerError(f"Container {container_id} not found")
            
            container_info = self.containers[container_id]
            
            if container_info.status != ContainerStatus.RUNNING:
                logger.warning(f"Container {container_id} is not running")
                return True
            
            # Update status
            container_info.status = ContainerStatus.STOPPING
            
            # Stop via API first
            if not force and container_id in self.processes:
                try:
                    api_socket = self.processes[container_id]["api_socket"]
                    await self._shutdown_microvm_via_api(api_socket)
                    
                    # Wait for graceful shutdown
                    process = self.processes[container_id]["process"]
                    try:
                        await asyncio.wait_for(process.wait(), timeout=10.0)
                    except asyncio.TimeoutError:
                        force = True
                        
                except Exception as e:
                    logger.warning(f"Graceful shutdown failed for {container_id}: {str(e)}")
                    force = True
            
            # Force kill if needed
            if force and container_id in self.processes:
                process = self.processes[container_id]["process"]
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            
            # Cleanup process reference
            if container_id in self.processes:
                del self.processes[container_id]
            
            # Cleanup networking
            await self.network_manager.cleanup_container_networking(container_id)
            
            # Stop security monitoring
            self.security_manager.stop_container_monitoring(container_id)
            
            # Update container status
            container_info.status = ContainerStatus.STOPPED
            container_info.stopped_at = time.strftime("%Y-%m-%d %H:%M:%S UTC")
            
            logger.info(f"Stopped Firecracker container {container_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop Firecracker container {container_id}: {str(e)}")
            raise FirecrackerError(f"Container stop failed: {str(e)}")
    
    async def destroy_container(self, container_id: str) -> bool:
        """Destroy a Firecracker microVM"""
        try:
            if container_id not in self.containers:
                raise FirecrackerError(f"Container {container_id} not found")
            
            # Stop container first if running
            container_info = self.containers[container_id]
            if container_info.status == ContainerStatus.RUNNING:
                await self.stop_container(container_id, force=True)
            
            # Cleanup volumes
            if hasattr(container_info, 'volume_ids'):
                for volume_id in container_info.volume_ids:
                    try:
                        await self.storage_manager.detach_volume(volume_id, container_id)
                        await self.storage_manager.delete_volume(volume_id)
                    except Exception as e:
                        logger.warning(f"Failed to cleanup volume {volume_id}: {str(e)}")
            
            # Cleanup networking
            await self.network_manager.cleanup_container_networking(container_id)
            
            # Remove container directory
            container_dir = self.runtime_path / container_id
            if container_dir.exists():
                import shutil
                shutil.rmtree(container_dir)
            
            # Remove from registry
            del self.containers[container_id]
            
            logger.info(f"Destroyed Firecracker container {container_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to destroy Firecracker container {container_id}: {str(e)}")
            raise FirecrackerError(f"Container destroy failed: {str(e)}")
    
    async def get_container_info(self, container_id: str) -> ContainerInfo:
        """Get container information"""
        if container_id not in self.containers:
            raise FirecrackerError(f"Container {container_id} not found")
        
        container_info = self.containers[container_id]
        
        # Update IP address if running
        if container_info.status == ContainerStatus.RUNNING and container_id in self.processes:
            try:
                api_socket = self.processes[container_id]["api_socket"]
                ip_address = await self._get_container_ip(api_socket)
                container_info.ip_address = ip_address
            except Exception as e:
                logger.debug(f"Could not get IP for container {container_id}: {str(e)}")
        
        return container_info
    
    async def list_containers(self, tenant_id: str = None, user_id: str = None) -> List[ContainerInfo]:
        """List containers with optional filtering"""
        containers = list(self.containers.values())
        
        if tenant_id:
            containers = [c for c in containers if c.tenant_id == tenant_id]
        
        if user_id:
            containers = [c for c in containers if c.user_id == user_id]
        
        return containers
    
    async def exec_command(self, container_id: str, command: List[str], 
                          timeout: int = 30) -> ExecResult:
        """Execute command in container (via SSH or agent)"""
        try:
            if container_id not in self.containers:
                raise FirecrackerError(f"Container {container_id} not found")
            
            container_info = self.containers[container_id]
            
            if container_info.status != ContainerStatus.RUNNING:
                raise FirecrackerError(f"Container {container_id} is not running")
            
            # For Firecracker, we need to use SSH or an agent inside the microVM
            # This is a simplified implementation - in production you'd use SSH
            start_time = time.time()
            
            # Placeholder implementation - would use SSH in production
            result = ExecResult(
                exit_code=0,
                stdout="Command executed successfully (placeholder)",
                stderr="",
                execution_time=time.time() - start_time
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to execute command in container {container_id}: {str(e)}")
            raise FirecrackerError(f"Command execution failed: {str(e)}")
    
    async def get_logs(self, container_id: str, lines: int = 100) -> str:
        """Get container logs"""
        try:
            if container_id not in self.containers:
                raise FirecrackerError(f"Container {container_id} not found")
            
            # Read logs from Firecracker process
            if container_id in self.processes:
                process = self.processes[container_id]["process"]
                # In production, you'd collect logs from the microVM
                return f"Logs for container {container_id} (last {lines} lines)"
            
            return f"No logs available for container {container_id}"
            
        except Exception as e:
            logger.error(f"Failed to get logs for container {container_id}: {str(e)}")
            raise FirecrackerError(f"Log retrieval failed: {str(e)}")
    
    async def get_metrics(self, container_id: str) -> Dict[str, Any]:
        """Get container resource metrics"""
        try:
            if container_id not in self.containers:
                raise FirecrackerError(f"Container {container_id} not found")
            
            metrics = {
                "container_id": container_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "cpu_usage_percent": 0.0,
                "memory_usage_mb": 0,
                "memory_usage_percent": 0.0,
                "disk_read_bytes": 0,
                "disk_write_bytes": 0,
                "network_rx_bytes": 0,
                "network_tx_bytes": 0
            }
            
            # Get metrics from Firecracker metrics socket
            if container_id in self.processes:
                try:
                    metrics_socket = self.processes[container_id]["metrics_socket"]
                    firecracker_metrics = await self._get_firecracker_metrics(metrics_socket)
                    metrics.update(firecracker_metrics)
                except Exception as e:
                    logger.debug(f"Could not get metrics for container {container_id}: {str(e)}")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get metrics for container {container_id}: {str(e)}")
            raise FirecrackerError(f"Metrics retrieval failed: {str(e)}")
    
    async def validate_config(self, config: ContainerConfig) -> bool:
        """Validate container configuration"""
        try:
            # Check required fields
            if not config.name or not config.template:
                return False
            
            # Check resource limits
            if config.memory_mb < 64 or config.memory_mb > 8192:
                return False
            
            if config.cpu_count < 1 or config.cpu_count > 16:
                return False
            
            if config.storage_gb < 0.1 or config.storage_gb > 100:
                return False
            
            # Firecracker doesn't support GPU
            if config.gpu_count > 0:
                return False
            
            # Check template exists (use TemplateManager)
            template_path = self.template_manager.get_template_path(config.template)
            if not template_path:
                # Try to download template if not found
                try:
                    downloaded = await self.template_manager.download_template(config.template)
                    if not downloaded:
                        return False
                except Exception:
                    # Fall back to legacy check for backward compatibility
                    template_file = self.rootfs_path / f"{config.template}.ext4"
                    if not template_file.exists():
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Configuration validation failed: {str(e)}")
            return False
    
    def get_supported_templates(self) -> List[Dict[str, str]]:
        """Get list of supported templates"""
        templates = []
        
        # Get templates from TemplateManager
        try:
            template_infos = self.template_manager.list_available_templates()
            for template_info in template_infos:
                templates.append({
                    "name": template_info.name,
                    "description": template_info.description,
                    "backend": "firecracker",
                    "version": template_info.version,
                    "architecture": template_info.architecture,
                    "os_family": template_info.os_family,
                    "security_level": template_info.security_level
                })
        except Exception as e:
            logger.warning(f"Failed to get templates from TemplateManager: {str(e)}")
            
            # Fall back to legacy scanning for backward compatibility
            if self.rootfs_path.exists():
                for rootfs_file in self.rootfs_path.glob("*.ext4"):
                    template_name = rootfs_file.stem
                    templates.append({
                        "name": template_name,
                        "description": f"Firecracker template: {template_name}",
                        "backend": "firecracker",
                        "path": str(rootfs_file)
                    })
        
        return templates
    
    async def _prepare_firecracker_config(self, container_id: str, config: ContainerConfig, 
                                         secured_config: Dict[str, Any],
                                         ip_address: str = None,
                                         volume_ids: List[str] = None) -> Dict[str, Any]:
        """Prepare Firecracker configuration"""
        # Get template rootfs (use TemplateManager)
        template_path = self.template_manager.get_template_path(config.template)
        if template_path:
            rootfs_file = template_path
        else:
            # Fall back to legacy path for backward compatibility
            rootfs_file = self.rootfs_path / f"{config.template}.ext4"
        
        kernel_file = self.kernel_path / "vmlinux-5.10"
        
        # Base configuration
        fc_config = {
            "boot-source": {
                "kernel_image_path": str(kernel_file),
                "boot_args": "console=ttyS0 reboot=k panic=1 pci=off nomodules random.trust_cpu=on"
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": str(rootfs_file),
                    "is_root_device": True,
                    "is_read_only": True
                }
            ],
            "machine-config": {
                "vcpu_count": config.cpu_count,
                "mem_size_mib": config.memory_mb,
                "ht_enabled": False,
                "cpu_template": "C3"
            },
            "network-interfaces": [
                {
                    "iface_id": "eth0",
                    "guest_mac": self._generate_mac_address(),
                    "host_dev_name": f"veth-{container_id[:12]}"
                }
            ]
        }
        
        # Add additional volumes from StorageManager
        if volume_ids:
            for i, volume_id in enumerate(volume_ids):
                try:
                    volume = self.storage_manager.volumes.get(volume_id)
                    if volume and volume.device_path:
                        fc_config["drives"].append({
                            "drive_id": f"volume_{i}",
                            "path_on_host": volume.device_path,
                            "is_root_device": False,
                            "is_read_only": False
                        })
                except Exception as e:
                    logger.warning(f"Failed to add volume {volume_id} to config: {str(e)}")
        
        # Apply security configuration
        fc_config.update(secured_config)
        
        return fc_config
    
    async def _wait_for_api_socket(self, api_socket: Path, timeout: int = 10):
        """Wait for Firecracker API socket to be ready"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if api_socket.exists():
                return
            await asyncio.sleep(0.1)
        
        raise FirecrackerError("API socket not ready within timeout")
    
    async def _configure_microvm_via_api(self, container_id: str, api_socket: Path):
        """Configure microVM via Firecracker API"""
        # Start the microVM
        try:
            await self._api_request(api_socket, "PUT", "/actions", {
                "action_type": "InstanceStart"
            })
        except Exception as e:
            logger.error(f"Failed to start microVM {container_id}: {str(e)}")
            raise
    
    async def _shutdown_microvm_via_api(self, api_socket: Path):
        """Shutdown microVM via API"""
        try:
            await self._api_request(api_socket, "PUT", "/actions", {
                "action_type": "SendCtrlAltDel"
            })
        except Exception as e:
            logger.warning(f"Failed to shutdown microVM gracefully: {str(e)}")
            raise
    
    async def _api_request(self, api_socket: Path, method: str, path: str, data: Dict = None):
        """Make request to Firecracker API"""
        # Use Unix socket connector for API requests
        connector = aiohttp.UnixConnector(path=str(api_socket))
        
        async with aiohttp.ClientSession(connector=connector) as session:
            url = f"http://localhost{path}"
            
            if method == "GET":
                async with session.get(url) as response:
                    return await response.json()
            elif method == "PUT":
                async with session.put(url, json=data) as response:
                    if response.status >= 400:
                        error_text = await response.text()
                        raise FirecrackerError(f"API request failed: {error_text}")
                    return await response.json() if response.content_type == "application/json" else None
    
    async def _get_container_ip(self, api_socket: Path) -> Optional[str]:
        """Get container IP address via API"""
        try:
            # This would query the network interface status
            # Placeholder implementation
            return "192.168.1.100"
        except Exception:
            return None
    
    async def _get_firecracker_metrics(self, metrics_socket: Path) -> Dict[str, Any]:
        """Get metrics from Firecracker metrics socket"""
        try:
            # Read metrics from Unix socket
            # Placeholder implementation
            return {
                "cpu_usage_percent": 15.5,
                "memory_usage_mb": 128,
                "memory_usage_percent": 25.0
            }
        except Exception:
            return {}
    
    def _generate_mac_address(self) -> str:
        """Generate random MAC address"""
        import random
        mac = [0x52, 0x54, 0x00,
               random.randint(0x00, 0x7f),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff)]
        return ':'.join(map(lambda x: "%02x" % x, mac))
    
    def _setup_process_security(self):
        """Set up security restrictions for Firecracker process"""
        # Drop privileges, set cgroups, etc.
        try:
            # Set process group
            os.setpgrp()
            
            # Limit resources (would use cgroups in production)
            import resource
            resource.setrlimit(resource.RLIMIT_NPROC, (100, 100))
            resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
            
        except Exception as e:
            logger.warning(f"Failed to set process security restrictions: {str(e)}")