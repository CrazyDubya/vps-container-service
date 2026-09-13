"""
Hardened LXC Backend Implementation
Manages LXC containers with security hardening and GPU support
"""

import json
import asyncio
import tempfile
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
import uuid
import time
import subprocess
import os
import yaml

from .base import ContainerBackend, ContainerConfig, ContainerInfo, ContainerStatus, ExecResult
from ..core.exceptions import LXCError, SecurityViolation, ConfigurationError
from ..core.security_manager import SecurityManager

logger = logging.getLogger(__name__)

class LXCBackend(ContainerBackend):
    """Hardened LXC container backend with GPU support"""
    
    def __init__(self, lxc_path: str = "/var/lib/lxc",
                 template_path: str = "/usr/share/lxc/templates",
                 config_path: str = "/etc/vps-secure-compute/lxc"):
        
        self.lxc_path = Path(lxc_path)
        self.template_path = Path(template_path)
        self.config_path = Path(config_path)
        self.security_manager = SecurityManager()
        
        # Container registry
        self.containers = {}
        
        # Ensure paths exist
        self.lxc_path.mkdir(parents=True, exist_ok=True)
        self.config_path.mkdir(parents=True, exist_ok=True)
        
        # Verify LXC is available
        self._verify_lxc_installation()
    
    async def create_container(self, config: ContainerConfig) -> str:
        """Create a new hardened LXC container"""
        try:
            # Generate unique container ID
            container_id = str(uuid.uuid4())
            container_name = f"vps-{container_id[:8]}"
            
            # Validate configuration
            if not self.validate_config(config):
                raise LXCError("Invalid container configuration")
            
            # Apply security hardening to configuration
            secured_config = self.security_manager.validate_container_config(
                "lxc", config.__dict__, config.user_context
            )
            
            # Create LXC container
            await self._create_lxc_container(container_name, config, secured_config)
            
            # Configure security hardening
            await self._apply_security_hardening(container_name, secured_config)
            
            # Configure GPU access if requested
            if config.gpu_count > 0:
                await self._configure_gpu_access(container_name, config.gpu_count)
            
            # Create container metadata
            container_info = ContainerInfo(
                id=container_id,
                name=config.name,
                status=ContainerStatus.CREATED,
                backend_type="lxc",
                memory_mb=config.memory_mb,
                cpu_count=config.cpu_count,
                storage_gb=config.storage_gb,
                gpu_count=config.gpu_count,
                ip_address=None,
                created_at=time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                started_at=None,
                stopped_at=None,
                user_id=config.user_context["user_id"],
                tenant_id=config.user_context["tenant_id"]
            )
            
            # Store container info with LXC name mapping
            self.containers[container_id] = {
                "info": container_info,
                "lxc_name": container_name
            }
            
            # Start security monitoring
            self.security_manager.monitor_container_security(container_id, config.user_context)
            
            logger.info(f"Created LXC container {container_id} ({container_name}) for user {config.user_context['user_id']}")
            return container_id
            
        except Exception as e:
            logger.error(f"Failed to create LXC container: {str(e)}")
            raise LXCError(f"Container creation failed: {str(e)}")
    
    async def start_container(self, container_id: str) -> bool:
        """Start an LXC container"""
        try:
            if container_id not in self.containers:
                raise LXCError(f"Container {container_id} not found")
            
            container_data = self.containers[container_id]
            container_info = container_data["info"]
            lxc_name = container_data["lxc_name"]
            
            if container_info.status != ContainerStatus.CREATED:
                raise LXCError(f"Container {container_id} is not in created state")
            
            # Update status
            container_info.status = ContainerStatus.STARTING
            
            # Start LXC container
            cmd = ["lxc-start", "-n", lxc_name, "-d"]
            result = await self._run_command(cmd)
            
            if result.returncode != 0:
                raise LXCError(f"Failed to start container: {result.stderr}")
            
            # Wait for container to be running
            await self._wait_for_container_state(lxc_name, "RUNNING")
            
            # Get IP address
            ip_address = await self._get_container_ip(lxc_name)
            
            # Update container status
            container_info.status = ContainerStatus.RUNNING
            container_info.started_at = time.strftime("%Y-%m-%d %H:%M:%S UTC")
            container_info.ip_address = ip_address
            
            logger.info(f"Started LXC container {container_id} ({lxc_name})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start LXC container {container_id}: {str(e)}")
            if container_id in self.containers:
                self.containers[container_id]["info"].status = ContainerStatus.FAILED
            raise LXCError(f"Container start failed: {str(e)}")
    
    async def stop_container(self, container_id: str, force: bool = False) -> bool:
        """Stop an LXC container"""
        try:
            if container_id not in self.containers:
                raise LXCError(f"Container {container_id} not found")
            
            container_data = self.containers[container_id]
            container_info = container_data["info"]
            lxc_name = container_data["lxc_name"]
            
            if container_info.status != ContainerStatus.RUNNING:
                logger.warning(f"Container {container_id} is not running")
                return True
            
            # Update status
            container_info.status = ContainerStatus.STOPPING
            
            # Stop LXC container
            if force:
                cmd = ["lxc-stop", "-n", lxc_name, "-k"]
            else:
                cmd = ["lxc-stop", "-n", lxc_name]
            
            result = await self._run_command(cmd)
            
            if result.returncode != 0:
                # Try force stop if graceful stop failed
                if not force:
                    logger.warning(f"Graceful stop failed for {container_id}, trying force stop")
                    return await self.stop_container(container_id, force=True)
                else:
                    raise LXCError(f"Failed to stop container: {result.stderr}")
            
            # Wait for container to be stopped
            await self._wait_for_container_state(lxc_name, "STOPPED")
            
            # Stop security monitoring
            self.security_manager.stop_container_monitoring(container_id)
            
            # Update container status
            container_info.status = ContainerStatus.STOPPED
            container_info.stopped_at = time.strftime("%Y-%m-%d %H:%M:%S UTC")
            container_info.ip_address = None
            
            logger.info(f"Stopped LXC container {container_id} ({lxc_name})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop LXC container {container_id}: {str(e)}")
            raise LXCError(f"Container stop failed: {str(e)}")
    
    async def destroy_container(self, container_id: str) -> bool:
        """Destroy an LXC container"""
        try:
            if container_id not in self.containers:
                raise LXCError(f"Container {container_id} not found")
            
            container_data = self.containers[container_id]
            container_info = container_data["info"]
            lxc_name = container_data["lxc_name"]
            
            # Stop container first if running
            if container_info.status == ContainerStatus.RUNNING:
                await self.stop_container(container_id, force=True)
            
            # Destroy LXC container
            cmd = ["lxc-destroy", "-n", lxc_name]
            result = await self._run_command(cmd)
            
            if result.returncode != 0:
                raise LXCError(f"Failed to destroy container: {result.stderr}")
            
            # Remove from registry
            del self.containers[container_id]
            
            logger.info(f"Destroyed LXC container {container_id} ({lxc_name})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to destroy LXC container {container_id}: {str(e)}")
            raise LXCError(f"Container destroy failed: {str(e)}")
    
    async def get_container_info(self, container_id: str) -> ContainerInfo:
        """Get container information"""
        if container_id not in self.containers:
            raise LXCError(f"Container {container_id} not found")
        
        container_data = self.containers[container_id]
        container_info = container_data["info"]
        lxc_name = container_data["lxc_name"]
        
        # Update status and IP if needed
        if container_info.status == ContainerStatus.RUNNING:
            try:
                state = await self._get_container_state(lxc_name)
                if state != "RUNNING":
                    container_info.status = ContainerStatus.STOPPED
                    container_info.ip_address = None
                else:
                    ip_address = await self._get_container_ip(lxc_name)
                    container_info.ip_address = ip_address
            except Exception as e:
                logger.debug(f"Could not update status for container {container_id}: {str(e)}")
        
        return container_info
    
    async def list_containers(self, tenant_id: str = None, user_id: str = None) -> List[ContainerInfo]:
        """List containers with optional filtering"""
        containers = [data["info"] for data in self.containers.values()]
        
        if tenant_id:
            containers = [c for c in containers if c.tenant_id == tenant_id]
        
        if user_id:
            containers = [c for c in containers if c.user_id == user_id]
        
        return containers
    
    async def exec_command(self, container_id: str, command: List[str], 
                          timeout: int = 30) -> ExecResult:
        """Execute command in LXC container"""
        try:
            if container_id not in self.containers:
                raise LXCError(f"Container {container_id} not found")
            
            container_data = self.containers[container_id]
            container_info = container_data["info"]
            lxc_name = container_data["lxc_name"]
            
            if container_info.status != ContainerStatus.RUNNING:
                raise LXCError(f"Container {container_id} is not running")
            
            # Execute command using lxc-attach
            cmd = ["lxc-attach", "-n", lxc_name, "--"] + command
            
            start_time = time.time()
            result = await self._run_command(cmd, timeout=timeout)
            execution_time = time.time() - start_time
            
            return ExecResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                execution_time=execution_time
            )
            
        except Exception as e:
            logger.error(f"Failed to execute command in container {container_id}: {str(e)}")
            raise LXCError(f"Command execution failed: {str(e)}")
    
    async def get_logs(self, container_id: str, lines: int = 100) -> str:
        """Get container logs"""
        try:
            if container_id not in self.containers:
                raise LXCError(f"Container {container_id} not found")
            
            container_data = self.containers[container_id]
            lxc_name = container_data["lxc_name"]
            
            # Get logs from LXC log file
            log_file = self.lxc_path / lxc_name / "lxc.log"
            
            if log_file.exists():
                cmd = ["tail", "-n", str(lines), str(log_file)]
                result = await self._run_command(cmd)
                return result.stdout
            
            return f"No logs available for container {container_id}"
            
        except Exception as e:
            logger.error(f"Failed to get logs for container {container_id}: {str(e)}")
            raise LXCError(f"Log retrieval failed: {str(e)}")
    
    async def get_metrics(self, container_id: str) -> Dict[str, Any]:
        """Get container resource metrics"""
        try:
            if container_id not in self.containers:
                raise LXCError(f"Container {container_id} not found")
            
            container_data = self.containers[container_id]
            lxc_name = container_data["lxc_name"]
            
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
            
            # Get metrics from cgroups
            try:
                cgroup_metrics = await self._get_cgroup_metrics(lxc_name)
                metrics.update(cgroup_metrics)
            except Exception as e:
                logger.debug(f"Could not get cgroup metrics for container {container_id}: {str(e)}")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get metrics for container {container_id}: {str(e)}")
            raise LXCError(f"Metrics retrieval failed: {str(e)}")
    
    def validate_config(self, config: ContainerConfig) -> bool:
        """Validate container configuration"""
        try:
            # Check required fields
            if not config.name or not config.template:
                return False
            
            # Check resource limits
            if config.memory_mb < 128 or config.memory_mb > 32768:
                return False
            
            if config.cpu_count < 1 or config.cpu_count > 32:
                return False
            
            if config.storage_gb < 1 or config.storage_gb > 1000:
                return False
            
            # Check GPU limits
            if config.gpu_count < 0 or config.gpu_count > 8:
                return False
            
            # Check template availability
            if not self._template_exists(config.template):
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Configuration validation failed: {str(e)}")
            return False
    
    def get_supported_templates(self) -> List[Dict[str, str]]:
        """Get list of supported templates"""
        templates = [
            {
                "name": "ubuntu-22.04",
                "description": "Ubuntu 22.04 LTS with security hardening",
                "backend": "lxc",
                "gpu_support": True
            },
            {
                "name": "pytorch-gpu",
                "description": "PyTorch with NVIDIA GPU support",
                "backend": "lxc",
                "gpu_support": True
            },
            {
                "name": "tensorflow-gpu",
                "description": "TensorFlow with NVIDIA GPU support",
                "backend": "lxc", 
                "gpu_support": True
            },
            {
                "name": "alpine-minimal",
                "description": "Alpine Linux minimal container",
                "backend": "lxc",
                "gpu_support": False
            }
        ]
        
        return templates
    
    def _verify_lxc_installation(self):
        """Verify LXC is properly installed"""
        try:
            result = subprocess.run(["lxc-ls", "--version"], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                raise ConfigurationError("LXC is not properly installed")
            
            logger.info(f"LXC version: {result.stdout.strip()}")
            
        except (subprocess.TimeoutExpired, FileNotFoundError):
            raise ConfigurationError("LXC is not installed or not in PATH")
    
    async def _create_lxc_container(self, container_name: str, config: ContainerConfig, 
                                   secured_config: Dict[str, Any]):
        """Create LXC container with template"""
        try:
            # Create container using template
            cmd = [
                "lxc-create",
                "-n", container_name,
                "-t", config.template,
                "--",
                "--release", "jammy",  # Default to Ubuntu 22.04
                "--arch", "amd64"
            ]
            
            result = await self._run_command(cmd, timeout=300)  # 5 minute timeout
            
            if result.returncode != 0:
                raise LXCError(f"Failed to create container: {result.stderr}")
            
        except Exception as e:
            logger.error(f"Failed to create LXC container {container_name}: {str(e)}")
            raise
    
    async def _apply_security_hardening(self, container_name: str, secured_config: Dict[str, Any]):
        """Apply security hardening to LXC container"""
        try:
            config_file = self.lxc_path / container_name / "config"
            
            # Read existing config
            if config_file.exists():
                with open(config_file, 'r') as f:
                    existing_config = f.read()
            else:
                existing_config = ""
            
            # Apply security hardening settings
            security_config = [
                "# Security hardening",
                "lxc.apparmor.profile = generated",
                "lxc.seccomp.profile = /etc/lxc/seccomp.policy",
                "lxc.idmap = u 0 100000 65536",
                "lxc.idmap = g 0 100000 65536",
                "",
                "# Capability restrictions",
                "lxc.cap.drop = sys_admin",
                "lxc.cap.drop = net_admin", 
                "lxc.cap.drop = sys_module",
                "lxc.cap.drop = sys_rawio",
                "lxc.cap.drop = audit_write",
                "lxc.cap.drop = audit_control",
                "",
                "# Mount restrictions",
                "lxc.mount.auto = proc:rw sys:ro cgroup:ro",
                "",
                "# Device restrictions",
                "lxc.cgroup2.devices.deny = a",
                "lxc.cgroup2.devices.allow = c 1:3 rwm",  # /dev/null
                "lxc.cgroup2.devices.allow = c 1:5 rwm",  # /dev/zero
                "lxc.cgroup2.devices.allow = c 5:0 rwm",  # /dev/tty
                "lxc.cgroup2.devices.allow = c 5:1 rwm",  # /dev/console
                "",
                "# Resource limits",
                "lxc.cgroup2.memory.max = 8G",
                "lxc.cgroup2.cpu.max = 400000 100000",
                ""
            ]
            
            # Write updated config
            with open(config_file, 'w') as f:
                f.write(existing_config)
                f.write('\n'.join(security_config))
            
            logger.info(f"Applied security hardening to container {container_name}")
            
        except Exception as e:
            logger.error(f"Failed to apply security hardening: {str(e)}")
            raise
    
    async def _configure_gpu_access(self, container_name: str, gpu_count: int):
        """Configure GPU access for container"""
        try:
            config_file = self.lxc_path / container_name / "config"
            
            gpu_config = [
                "# GPU access configuration",
                "lxc.cgroup2.devices.allow = c 195:* rwm",  # NVIDIA devices
                "lxc.cgroup2.devices.allow = c 510:* rwm",  # NVIDIA UVM
                "",
                "# NVIDIA device mounts",
                "lxc.mount.entry = /dev/nvidia0 dev/nvidia0 none bind,optional,create=file",
                "lxc.mount.entry = /dev/nvidiactl dev/nvidiactl none bind,optional,create=file",
                "lxc.mount.entry = /dev/nvidia-uvm dev/nvidia-uvm none bind,optional,create=file",
                "lxc.mount.entry = /dev/nvidia-uvm-tools dev/nvidia-uvm-tools none bind,optional,create=file",
                "",
                "# NVIDIA runtime libraries",
                "lxc.mount.entry = /usr/lib/x86_64-linux-gnu/libnvidia-ml.so usr/lib/x86_64-linux-gnu/libnvidia-ml.so none bind,optional,ro",
                ""
            ]
            
            # Append GPU configuration
            with open(config_file, 'a') as f:
                f.write('\n'.join(gpu_config))
            
            logger.info(f"Configured GPU access for container {container_name} ({gpu_count} GPUs)")
            
        except Exception as e:
            logger.error(f"Failed to configure GPU access: {str(e)}")
            raise
    
    async def _run_command(self, cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Run command asynchronously"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=process.returncode,
                stdout=stdout.decode() if stdout else "",
                stderr=stderr.decode() if stderr else ""
            )
            
        except asyncio.TimeoutError:
            logger.error(f"Command timeout: {' '.join(cmd)}")
            raise LXCError(f"Command timeout: {' '.join(cmd)}")
        except Exception as e:
            logger.error(f"Command failed: {' '.join(cmd)}: {str(e)}")
            raise LXCError(f"Command failed: {str(e)}")
    
    async def _wait_for_container_state(self, container_name: str, expected_state: str, timeout: int = 30):
        """Wait for container to reach expected state"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                state = await self._get_container_state(container_name)
                if state == expected_state:
                    return
                await asyncio.sleep(1)
            except Exception:
                await asyncio.sleep(1)
        
        raise LXCError(f"Container {container_name} did not reach state {expected_state} within {timeout}s")
    
    async def _get_container_state(self, container_name: str) -> str:
        """Get container state"""
        cmd = ["lxc-info", "-n", container_name, "-s"]
        result = await self._run_command(cmd)
        
        if result.returncode != 0:
            raise LXCError(f"Failed to get container state: {result.stderr}")
        
        # Parse state from output (e.g., "State: RUNNING")
        for line in result.stdout.split('\n'):
            if line.startswith('State:'):
                return line.split()[-1]
        
        return "UNKNOWN"
    
    async def _get_container_ip(self, container_name: str) -> Optional[str]:
        """Get container IP address"""
        try:
            cmd = ["lxc-info", "-n", container_name, "-i"]
            result = await self._run_command(cmd)
            
            if result.returncode == 0:
                # Parse IP from output
                for line in result.stdout.split('\n'):
                    if 'IP:' in line:
                        ip = line.split()[-1]
                        if ip != '-':
                            return ip
            
            return None
            
        except Exception:
            return None
    
    async def _get_cgroup_metrics(self, container_name: str) -> Dict[str, Any]:
        """Get metrics from cgroups"""
        metrics = {}
        
        try:
            # Get memory usage
            memory_file = f"/sys/fs/cgroup/lxc/{container_name}/memory.current"
            if os.path.exists(memory_file):
                with open(memory_file, 'r') as f:
                    memory_bytes = int(f.read().strip())
                    metrics["memory_usage_mb"] = memory_bytes // (1024 * 1024)
            
            # Get CPU usage (simplified)
            cpu_file = f"/sys/fs/cgroup/lxc/{container_name}/cpu.stat"
            if os.path.exists(cpu_file):
                with open(cpu_file, 'r') as f:
                    for line in f:
                        if line.startswith('usage_usec'):
                            usage_usec = int(line.split()[1])
                            # Convert to percentage (simplified)
                            metrics["cpu_usage_percent"] = min(100.0, usage_usec / 10000)
                            break
            
        except Exception as e:
            logger.debug(f"Failed to get cgroup metrics: {str(e)}")
        
        return metrics
    
    def _template_exists(self, template: str) -> bool:
        """Check if template exists"""
        # For now, assume templates exist if they're in our supported list
        supported = [t["name"] for t in self.get_supported_templates()]
        return template in supported