"""
Docker Container Converter
Intelligent conversion of Docker containers to Firecracker or LXC backends
with automated backend selection based on GPU, hardware, and performance requirements
"""

import json
import asyncio
import tempfile
import logging
import subprocess
import shlex
import re
from typing import Dict, List, Any, Optional, Tuple, Union
from pathlib import Path
import yaml
import hashlib
from dataclasses import dataclass, asdict
from enum import Enum

from .exceptions import ConversionError, ConfigurationError
from .template_manager import TemplateManager
from .storage_manager import StorageManager
from .network_manager import NetworkManager
from ..backends.base import ContainerConfig
from ..backends.firecracker import FirecrackerBackend
from ..backends.lxc import LXCBackend

logger = logging.getLogger(__name__)

class BackendType(Enum):
    """Available container backends"""
    FIRECRACKER = "firecracker"
    LXC = "lxc"
    AUTO = "auto"

@dataclass
class DockerImageInfo:
    """Docker image analysis results"""
    name: str
    tag: str
    size_mb: int
    layers: List[str]
    exposed_ports: List[int]
    volumes: List[str]
    env_vars: Dict[str, str]
    commands: List[str]
    gpu_required: bool
    privileged_required: bool
    network_mode: str
    base_os: str
    architecture: str
    packages: List[str]
    cuda_version: Optional[str] = None
    opencl_support: bool = False

@dataclass
class ConversionRules:
    """Rules for backend selection"""
    prefer_firecracker_if: List[str]
    prefer_lxc_if: List[str]
    force_firecracker_if: List[str]
    force_lxc_if: List[str]
    performance_thresholds: Dict[str, int]

class DockerConverter:
    """
    Intelligent Docker-to-Container converter with automatic backend selection
    
    Features:
    - Analyzes Docker images for hardware requirements
    - Automatically selects optimal backend (Firecracker vs LXC)
    - Converts Docker configurations to native backend formats
    - Preserves security and isolation requirements
    - Handles GPU, networking, and storage requirements
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        templates_config = config.get('templates', {})
        self.template_manager = TemplateManager(
            template_path=templates_config.get('path', '/opt/vps-secure-compute/templates'),
            registry_url=templates_config.get('registry_url', 'https://templates.vps-secure.com')
        )
        
        storage_config = config.get('storage', {})
        self.storage_manager = StorageManager(
            storage_path=storage_config.get('path', '/opt/vps-secure-compute/storage'),
            backup_path=storage_config.get('backup_path', '/opt/vps-secure-compute/backups'),
            encryption_enabled=storage_config.get('encryption_enabled', True)
        )
        
        self.network_manager = NetworkManager()
        
        # Initialize backends
        firecracker_config = config.get('firecracker', {})
        self.firecracker_backend = FirecrackerBackend(
            firecracker_binary=firecracker_config.get('binary', '/usr/bin/firecracker'),
            kernel_path=firecracker_config.get('kernel_path', '/opt/firecracker/kernels'),
            rootfs_path=firecracker_config.get('rootfs_path', '/opt/firecracker/rootfs'),
            runtime_path=firecracker_config.get('runtime_path', '/var/run/vps-secure-compute'),
            template_manager=self.template_manager,
            network_manager=self.network_manager,
            storage_manager=self.storage_manager
        )
        
        lxc_config = config.get('lxc', {})
        self.lxc_backend = LXCBackend(
            lxc_path=lxc_config.get('path', '/var/lib/lxc'),
            template_path=lxc_config.get('template_path', '/usr/share/lxc/templates'),
            config_path=lxc_config.get('config_path', '/etc/vps-secure-compute/lxc')
        )
        
        # Load conversion rules
        self.conversion_rules = self._load_conversion_rules()
        
        # Docker client verification
        self._verify_docker_available()
    
    def _load_conversion_rules(self) -> ConversionRules:
        """Load backend selection rules"""
        return ConversionRules(
            prefer_firecracker_if=[
                "high_isolation_required",
                "micro_service",
                "serverless_workload",
                "fast_startup_required",
                "minimal_overhead",
                "untrusted_code"
            ],
            prefer_lxc_if=[
                "gpu_required",
                "large_memory_footprint",
                "system_containers",
                "legacy_applications",
                "complex_networking",
                "persistent_storage_heavy"
            ],
            force_firecracker_if=[
                "maximum_isolation",
                "hostile_multi_tenant",
                "serverless_functions",
                "ephemeral_workload"
            ],
            force_lxc_if=[
                "cuda_required",
                "opencl_required",
                "gpu_passthrough",
                "privileged_operations",
                "systemd_required",
                "kernel_modules"
            ],
            performance_thresholds={
                "memory_mb_firecracker_limit": 8192,  # Above this, prefer LXC
                "cpu_count_firecracker_limit": 8,     # Above this, prefer LXC
                "storage_gb_firecracker_limit": 50,   # Above this, prefer LXC
                "startup_time_ms_requirement": 500,   # Below this, prefer Firecracker
            }
        )
    
    def _verify_docker_available(self):
        """Verify Docker is available for image analysis"""
        try:
            result = subprocess.run(['docker', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                logger.warning("Docker not available for image analysis")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Docker not available for image analysis")
    
    async def analyze_docker_image(self, image_name: str) -> DockerImageInfo:
        """
        Analyze Docker image to determine requirements and characteristics
        """
        logger.info(f"Analyzing Docker image: {image_name}")
        
        try:
            # Get image details via docker inspect
            image_info = await self._inspect_docker_image(image_name)
            
            # Analyze layers and configuration
            layers = await self._analyze_image_layers(image_name)
            
            # Detect GPU requirements
            gpu_required = await self._detect_gpu_requirements(image_name, image_info)
            
            # Detect privileged requirements
            privileged_required = await self._detect_privileged_requirements(image_info)
            
            # Analyze base OS and packages
            base_os, packages = await self._analyze_base_os_and_packages(image_name)
            
            # Extract configuration
            config = image_info.get('Config', {})
            
            return DockerImageInfo(
                name=image_name.split(':')[0],
                tag=image_name.split(':')[1] if ':' in image_name else 'latest',
                size_mb=self._bytes_to_mb(image_info.get('Size', 0)),
                layers=layers,
                exposed_ports=self._extract_ports(config.get('ExposedPorts', {})),
                volumes=list(config.get('Volumes', {}).keys()),
                env_vars=self._parse_env_vars(config.get('Env', [])),
                commands=config.get('Cmd', []) or config.get('Entrypoint', []),
                gpu_required=gpu_required,
                privileged_required=privileged_required,
                network_mode="bridge",  # Default, can be overridden
                base_os=base_os,
                architecture=image_info.get('Architecture', 'amd64'),
                packages=packages,
                cuda_version=await self._detect_cuda_version(image_name),
                opencl_support=await self._detect_opencl_support(image_name)
            )
            
        except Exception as e:
            logger.error(f"Failed to analyze Docker image {image_name}: {e}")
            raise ConversionError(f"Image analysis failed: {e}")
    
    async def _inspect_docker_image(self, image_name: str) -> Dict[str, Any]:
        """Get Docker image details"""
        try:
            cmd = ['docker', 'inspect', image_name]
            result = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                raise ConversionError(f"Docker inspect failed: {stderr.decode()}")
            
            images = json.loads(stdout.decode())
            if not images:
                raise ConversionError(f"Image {image_name} not found")
            
            return images[0]
            
        except json.JSONDecodeError as e:
            raise ConversionError(f"Invalid Docker inspect output: {e}")
        except Exception as e:
            raise ConversionError(f"Docker inspect failed: {e}")
    
    async def _analyze_image_layers(self, image_name: str) -> List[str]:
        """Analyze Docker image layers"""
        try:
            cmd = ['docker', 'history', '--no-trunc', '--format', 'json', image_name]
            result = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                logger.warning(f"Failed to get image history: {stderr.decode()}")
                return []
            
            layers = []
            for line in stdout.decode().strip().split('\n'):
                if line:
                    layer_info = json.loads(line)
                    layers.append(layer_info.get('CreatedBy', ''))
            
            return layers
            
        except Exception as e:
            logger.warning(f"Failed to analyze image layers: {e}")
            return []
    
    async def _detect_gpu_requirements(self, image_name: str, image_info: Dict) -> bool:
        """Detect if container requires GPU access"""
        # Check for NVIDIA runtime requirements
        gpu_indicators = [
            'nvidia', 'cuda', 'cudnn', 'tensorrt', 'gpu',
            'pytorch', 'tensorflow-gpu', 'cupy', 'rapids'
        ]
        
        # Check image name and labels
        image_lower = image_name.lower()
        if any(indicator in image_lower for indicator in gpu_indicators):
            return True
        
        # Check environment variables
        env_vars = self._parse_env_vars(image_info.get('Config', {}).get('Env', []))
        for env_var, value in env_vars.items():
            if any(indicator in env_var.lower() or indicator in value.lower() 
                   for indicator in gpu_indicators):
                return True
        
        # Check labels
        labels = image_info.get('Config', {}).get('Labels', {}) or {}
        for label, value in labels.items():
            if any(indicator in label.lower() or indicator in str(value).lower() 
                   for indicator in gpu_indicators):
                return True
        
        return False
    
    async def _detect_privileged_requirements(self, image_info: Dict) -> bool:
        """Detect if container requires privileged access"""
        config = image_info.get('Config', {})
        
        # Check for privileged indicators
        privileged_indicators = [
            'systemd', 'systemctl', 'dbus', 'udev', 'docker', 'kubernetes',
            'privileged', 'cap_add', 'security-opt', 'init', '/sbin/init', '/usr/sbin/init'
        ]
        
        # Check commands and entrypoints
        commands = config.get('Cmd', []) + config.get('Entrypoint', [])
        for cmd in commands:
            if isinstance(cmd, str) and any(indicator in cmd.lower() 
                                          for indicator in privileged_indicators):
                return True
        
        # Check environment variables
        env_vars = self._parse_env_vars(config.get('Env', []))
        for env_var, value in env_vars.items():
            if any(indicator in env_var.lower() or indicator in value.lower() 
                   for indicator in privileged_indicators):
                return True
        
        return False
    
    async def _analyze_base_os_and_packages(self, image_name: str) -> Tuple[str, List[str]]:
        """Analyze base OS and installed packages"""
        # Common base OS patterns
        os_patterns = {
            'ubuntu': r'ubuntu|focal|bionic|xenial|jammy',
            'debian': r'debian|buster|bullseye|bookworm',
            'alpine': r'alpine|musl',
            'centos': r'centos|rhel|rocky|alma',
            'fedora': r'fedora',
            'arch': r'arch|manjaro'
        }
        
        image_lower = image_name.lower()
        detected_os = 'unknown'
        
        for os_name, pattern in os_patterns.items():
            if re.search(pattern, image_lower):
                detected_os = os_name
                break
        
        # Try to detect packages (simplified)
        packages = []
        package_indicators = [
            'python', 'node', 'java', 'golang', 'rust', 'ruby',
            'nginx', 'apache', 'mysql', 'postgresql', 'redis',
            'cuda', 'opencv', 'tensorflow', 'pytorch'
        ]
        
        for indicator in package_indicators:
            if indicator in image_lower:
                packages.append(indicator)
        
        return detected_os, packages
    
    async def _detect_cuda_version(self, image_name: str) -> Optional[str]:
        """Detect CUDA version if present"""
        cuda_pattern = r'cuda[:\-_]?(\d+\.?\d*)'
        match = re.search(cuda_pattern, image_name.lower())
        if match:
            return match.group(1)
        return None
    
    async def _detect_opencl_support(self, image_name: str) -> bool:
        """Detect OpenCL support"""
        opencl_indicators = ['opencl', 'cl_', 'khronos']
        return any(indicator in image_name.lower() for indicator in opencl_indicators)
    
    def _extract_ports(self, exposed_ports: Dict) -> List[int]:
        """Extract port numbers from Docker exposed ports"""
        ports = []
        for port_spec in exposed_ports.keys():
            port = port_spec.split('/')[0]
            try:
                ports.append(int(port))
            except ValueError:
                continue
        return ports
    
    def _parse_env_vars(self, env_list: List[str]) -> Dict[str, str]:
        """Parse Docker environment variables"""
        env_vars = {}
        for env_str in env_list:
            if '=' in env_str:
                key, value = env_str.split('=', 1)
                env_vars[key] = value
        return env_vars
    
    def _bytes_to_mb(self, bytes_size: int) -> int:
        """Convert bytes to megabytes"""
        return int(bytes_size / (1024 * 1024))
    
    async def select_optimal_backend(self, 
                                   image_info: DockerImageInfo,
                                   user_preference: BackendType = BackendType.AUTO,
                                   performance_requirements: Optional[Dict] = None) -> BackendType:
        """
        Intelligently select the optimal backend for the container
        """
        logger.info(f"Selecting backend for {image_info.name}:{image_info.tag}")
        
        # Handle explicit user preference
        if user_preference in [BackendType.FIRECRACKER, BackendType.LXC]:
            logger.info(f"Using user-specified backend: {user_preference.value}")
            return user_preference
        
        # Check force rules first
        if self._check_force_rules(image_info):
            return self._get_forced_backend(image_info)
        
        # Score-based selection
        firecracker_score = await self._calculate_firecracker_score(
            image_info, performance_requirements
        )
        lxc_score = await self._calculate_lxc_score(
            image_info, performance_requirements
        )
        
        logger.info(f"Backend scores - Firecracker: {firecracker_score}, LXC: {lxc_score}")
        
        # Select backend with higher score
        if firecracker_score >= lxc_score:
            return BackendType.FIRECRACKER
        else:
            return BackendType.LXC
    
    def _check_force_rules(self, image_info: DockerImageInfo) -> bool:
        """Check if any force rules apply"""
        # GPU requirements force LXC
        if image_info.gpu_required or image_info.cuda_version or image_info.opencl_support:
            return True
        
        # Privileged requirements force LXC
        if image_info.privileged_required:
            return True
        
        # Large resource requirements
        thresholds = self.conversion_rules.performance_thresholds
        if (image_info.size_mb > thresholds['memory_mb_firecracker_limit'] * 4):
            return True
        
        # Check package-based rules
        force_lxc_packages = ['systemd', 'docker', 'kubernetes', 'nvidia']
        if any(pkg in image_info.packages for pkg in force_lxc_packages):
            return True
        
        return False
    
    def _get_forced_backend(self, image_info: DockerImageInfo) -> BackendType:
        """Determine which backend is forced"""
        # GPU or privileged always forces LXC
        if (image_info.gpu_required or image_info.privileged_required or 
            image_info.cuda_version or image_info.opencl_support):
            return BackendType.LXC
        
        # Large containers force LXC
        thresholds = self.conversion_rules.performance_thresholds
        if image_info.size_mb > thresholds['memory_mb_firecracker_limit'] * 4:
            return BackendType.LXC
        
        return BackendType.LXC  # Default for forced cases
    
    async def _calculate_firecracker_score(self, 
                                         image_info: DockerImageInfo,
                                         performance_requirements: Optional[Dict]) -> int:
        """Calculate score for Firecracker backend"""
        score = 50  # Base score
        
        # Positive factors for Firecracker
        if image_info.size_mb < 512:
            score += 20  # Small images
        
        if len(image_info.commands) == 1:
            score += 15  # Single command/microservice
        
        if not image_info.privileged_required:
            score += 25  # No privileged access needed
        
        if not image_info.gpu_required:
            score += 30  # No GPU required
        
        if image_info.base_os in ['alpine', 'scratch']:
            score += 15  # Minimal base OS
        
        # Performance requirements
        if performance_requirements:
            if performance_requirements.get('startup_time_ms', 1000) < 500:
                score += 20  # Fast startup required
            
            if performance_requirements.get('isolation_level') == 'maximum':
                score += 25  # Maximum isolation
        
        # Negative factors
        if image_info.size_mb > 2048:
            score -= 20  # Large images
        
        if len(image_info.volumes) > 3:
            score -= 10  # Many volumes
        
        if image_info.base_os == 'unknown':
            score -= 15  # Unknown base OS
        
        return max(0, score)
    
    async def _calculate_lxc_score(self, 
                                 image_info: DockerImageInfo,
                                 performance_requirements: Optional[Dict]) -> int:
        """Calculate score for LXC backend"""
        score = 50  # Base score
        
        # Positive factors for LXC
        if image_info.gpu_required:
            score += 40  # GPU support
        
        if image_info.privileged_required:
            score += 30  # Privileged operations
        
        if image_info.size_mb > 1024:
            score += 15  # Large images benefit from LXC
        
        if len(image_info.volumes) > 2:
            score += 10  # Multiple volumes
        
        if image_info.base_os in ['ubuntu', 'debian', 'centos']:
            score += 15  # Full OS distributions
        
        if 'systemd' in image_info.packages:
            score += 20  # System services
        
        # Performance requirements
        if performance_requirements:
            if performance_requirements.get('memory_gb', 1) > 4:
                score += 15  # High memory requirements
            
            if performance_requirements.get('cpu_count', 1) > 4:
                score += 15  # High CPU requirements
        
        # Negative factors
        if image_info.size_mb < 100:
            score -= 15  # Very small images
        
        if len(image_info.commands) == 1 and not image_info.volumes:
            score -= 10  # Simple microservices
        
        return max(0, score)
    
    async def convert_to_container_config(self, 
                                        image_info: DockerImageInfo,
                                        backend_type: BackendType,
                                        container_name: str,
                                        user_overrides: Optional[Dict] = None) -> ContainerConfig:
        """
        Convert Docker image info to native container configuration
        """
        logger.info(f"Converting {image_info.name} to {backend_type.value} configuration")
        
        # Base configuration
        config_dict = {
            'name': container_name,
            'template': await self._select_template(image_info, backend_type),
            'memory_mb': self._calculate_memory_requirements(image_info),
            'cpu_count': self._calculate_cpu_requirements(image_info),
            'storage_gb': self._calculate_storage_requirements(image_info),
            'gpu_count': 1 if image_info.gpu_required else 0,
            'network_config': {'mode': 'bridge', 'ports': image_info.exposed_ports},
            'security_config': {'privileged': image_info.privileged_required},
            'environment': image_info.env_vars,
            'volumes': [{'container_path': vol, 'type': 'bind'} for vol in image_info.volumes],
            'user_context': {
                'gpu_enabled': image_info.gpu_required,
                'privileged': image_info.privileged_required,
                'backend_type': backend_type.value,
                'metadata': {
                    'source_image': f"{image_info.name}:{image_info.tag}",
                    'conversion_method': 'docker_converter',
                    'gpu_required': image_info.gpu_required,
                    'base_os': image_info.base_os
                }
            }
        }
        
        # Backend-specific configurations
        if backend_type == BackendType.FIRECRACKER:
            fc_config = await self._add_firecracker_config(image_info)
            config_dict['user_context'].update(fc_config)
        else:
            lxc_config = await self._add_lxc_config(image_info)
            config_dict['user_context'].update(lxc_config)
        
        # Apply user overrides
        if user_overrides:
            config_dict.update(user_overrides)
        
        # Create container config
        container_config = ContainerConfig(**config_dict)
        
        # Add convenience properties as attributes for compatibility
        container_config.gpu_enabled = image_info.gpu_required
        container_config.privileged = image_info.privileged_required  
        container_config.backend_type = backend_type.value
        container_config.metadata = container_config.user_context['metadata']
        
        return container_config
    
    async def _select_template(self, image_info: DockerImageInfo, backend_type: BackendType) -> str:
        """Select appropriate template based on image info"""
        # Map base OS to templates
        os_template_map = {
            'ubuntu': 'ubuntu-22.04',
            'debian': 'debian-11',
            'alpine': 'alpine-3.18',
            'centos': 'centos-8',
            'fedora': 'fedora-38'
        }
        
        base_template = os_template_map.get(image_info.base_os, 'ubuntu-22.04')
        
        # Add GPU suffix if needed
        if image_info.gpu_required:
            base_template += '-gpu'
        
        return base_template
    
    def _calculate_memory_requirements(self, image_info: DockerImageInfo) -> int:
        """Calculate memory requirements in MB"""
        # Base memory + image size overhead
        base_memory = 512
        image_overhead = max(256, image_info.size_mb // 2)
        
        # Adjust for specific packages
        if 'java' in image_info.packages:
            base_memory += 512
        if 'python' in image_info.packages:
            base_memory += 256
        if any(pkg in image_info.packages for pkg in ['tensorflow', 'pytorch']):
            base_memory += 1024
        
        return base_memory + image_overhead
    
    def _calculate_cpu_requirements(self, image_info: DockerImageInfo) -> int:
        """Calculate CPU requirements"""
        base_cpu = 1
        
        # Adjust for compute-intensive packages
        if any(pkg in image_info.packages for pkg in ['tensorflow', 'pytorch', 'cuda']):
            base_cpu = 2
        if 'java' in image_info.packages:
            base_cpu = max(base_cpu, 2)
        
        return base_cpu
    
    def _calculate_storage_requirements(self, image_info: DockerImageInfo) -> int:
        """Calculate storage requirements in GB"""
        # Base storage + image size + working space
        base_storage = 10
        image_storage = max(2, (image_info.size_mb // 1024) + 1)
        working_space = 5
        
        # Add extra space for volumes
        volume_space = len(image_info.volumes) * 2
        
        return base_storage + image_storage + working_space + volume_space
    
    async def _add_firecracker_config(self, image_info: DockerImageInfo) -> Dict[str, Any]:
        """Add Firecracker-specific configuration"""
        return {
            'boot_timeout': 30,
            'kernel_args': 'console=ttyS0 reboot=k panic=1 pci=off'
        }
    
    async def _add_lxc_config(self, image_info: DockerImageInfo) -> Dict[str, Any]:
        """Add LXC-specific configuration"""
        config = {
            'security_profile': 'default'
        }
        
        # GPU configuration
        if image_info.gpu_required:
            config['gpu_config'] = {
                'enabled': True,
                'devices': ['nvidia.com/gpu=all'],
                'cuda_version': image_info.cuda_version
            }
        
        # Privileged configuration
        if image_info.privileged_required:
            config['security_profile'] = 'privileged'
            config['capabilities'] = ['SYS_ADMIN', 'NET_ADMIN']
        
        return config
    
    async def convert_docker_container(self, 
                                     image_name: str,
                                     container_name: str,
                                     backend_preference: BackendType = BackendType.AUTO,
                                     performance_requirements: Optional[Dict] = None,
                                     user_overrides: Optional[Dict] = None) -> Tuple[ContainerConfig, BackendType]:
        """
        Complete Docker container conversion workflow
        
        Returns:
            Tuple of (ContainerConfig, selected_backend)
        """
        logger.info(f"Starting conversion of Docker image: {image_name}")
        
        try:
            # Step 1: Analyze Docker image
            image_info = await self.analyze_docker_image(image_name)
            try:
                logger.info(f"Image analysis complete: {asdict(image_info)}")
            except TypeError:
                # Handle mock objects during testing
                logger.info(f"Image analysis complete: {image_info.name}:{image_info.tag}")
            
            # Step 2: Select optimal backend
            selected_backend = await self.select_optimal_backend(
                image_info, backend_preference, performance_requirements
            )
            logger.info(f"Selected backend: {selected_backend.value}")
            
            # Step 3: Generate container configuration
            container_config = await self.convert_to_container_config(
                image_info, selected_backend, container_name, user_overrides
            )
            
            logger.info(f"Conversion complete: {container_name} -> {selected_backend.value}")
            return container_config, selected_backend
            
        except Exception as e:
            logger.error(f"Conversion failed for {image_name}: {e}")
            raise ConversionError(f"Docker conversion failed: {e}")
    
    async def create_converted_container(self, 
                                       image_name: str,
                                       container_name: str,
                                       backend_preference: BackendType = BackendType.AUTO,
                                       performance_requirements: Optional[Dict] = None,
                                       user_overrides: Optional[Dict] = None) -> str:
        """
        Convert Docker container and create it in the selected backend
        
        Returns:
            Container ID
        """
        # Convert configuration
        config, backend_type = await self.convert_docker_container(
            image_name, container_name, backend_preference, 
            performance_requirements, user_overrides
        )
        
        # Create container in selected backend
        if backend_type == BackendType.FIRECRACKER:
            container_id = await self.firecracker_backend.create_container(config)
        else:
            container_id = await self.lxc_backend.create_container(config)
        
        logger.info(f"Created container {container_id} from Docker image {image_name}")
        return container_id
    
    async def batch_convert_compose_file(self, compose_file_path: str) -> Dict[str, Tuple[ContainerConfig, BackendType]]:
        """
        Convert an entire Docker Compose file to native containers
        
        Returns:
            Dictionary mapping service names to (config, backend) tuples
        """
        logger.info(f"Converting Docker Compose file: {compose_file_path}")
        
        try:
            with open(compose_file_path, 'r') as f:
                compose_data = yaml.safe_load(f)
            
            services = compose_data.get('services', {})
            converted_services = {}
            
            for service_name, service_config in services.items():
                image_name = service_config.get('image')
                if not image_name:
                    logger.warning(f"Skipping service {service_name}: no image specified")
                    continue
                
                # Extract performance requirements from compose config
                performance_req = {
                    'memory_gb': self._parse_compose_memory(service_config.get('mem_limit')),
                    'cpu_count': self._parse_compose_cpus(service_config.get('cpus')),
                    'startup_time_ms': 1000  # Default
                }
                
                # Extract user overrides
                overrides = {
                    'network_config': {'ports': self._parse_compose_ports(service_config.get('ports', []))},
                    'environment': service_config.get('environment', {}),
                    'volumes': self._parse_compose_volumes(service_config.get('volumes', []))
                }
                
                # Convert service
                config, backend = await self.convert_docker_container(
                    image_name, service_name, BackendType.AUTO, 
                    performance_req, overrides
                )
                
                converted_services[service_name] = (config, backend)
            
            logger.info(f"Converted {len(converted_services)} services from Docker Compose")
            return converted_services
            
        except Exception as e:
            logger.error(f"Failed to convert Docker Compose file: {e}")
            raise ConversionError(f"Compose conversion failed: {e}")
    
    def _parse_compose_memory(self, mem_limit: Optional[str]) -> int:
        """Parse Docker Compose memory limit"""
        if not mem_limit:
            return 1
        
        # Parse formats like "1g", "512m", "1024"
        if mem_limit.endswith('g'):
            return int(float(mem_limit[:-1]))
        elif mem_limit.endswith('m'):
            return int(float(mem_limit[:-1]) / 1024)
        else:
            return int(int(mem_limit) / (1024 * 1024 * 1024))
    
    def _parse_compose_cpus(self, cpus: Optional[Union[str, float]]) -> int:
        """Parse Docker Compose CPU limit"""
        if not cpus:
            return 1
        return max(1, int(float(cpus)))
    
    def _parse_compose_ports(self, ports: List[str]) -> List[Dict[str, int]]:
        """Parse Docker Compose port mappings"""
        parsed_ports = []
        for port_spec in ports:
            if ':' in str(port_spec):
                host_port, container_port = str(port_spec).split(':')
                parsed_ports.append({
                    'host_port': int(host_port),
                    'container_port': int(container_port),
                    'protocol': 'tcp'
                })
        return parsed_ports
    
    def _parse_compose_volumes(self, volumes: List[str]) -> List[Dict[str, str]]:
        """Parse Docker Compose volume mappings"""
        parsed_volumes = []
        for volume_spec in volumes:
            if ':' in volume_spec:
                host_path, container_path = volume_spec.split(':', 1)
                parsed_volumes.append({
                    'host_path': host_path,
                    'container_path': container_path,
                    'read_only': volume_spec.endswith(':ro')
                })
        return parsed_volumes
    
    async def get_conversion_recommendations(self, image_name: str) -> Dict[str, Any]:
        """
        Get conversion recommendations for a Docker image
        """
        image_info = await self.analyze_docker_image(image_name)
        
        # Get scores for both backends
        firecracker_score = await self._calculate_firecracker_score(image_info, None)
        lxc_score = await self._calculate_lxc_score(image_info, None)
        
        recommendations = {
            'image_analysis': asdict(image_info),
            'backend_scores': {
                'firecracker': firecracker_score,
                'lxc': lxc_score
            },
            'recommended_backend': 'firecracker' if firecracker_score >= lxc_score else 'lxc',
            'requirements': {
                'memory_mb': self._calculate_memory_requirements(image_info),
                'cpu_count': self._calculate_cpu_requirements(image_info),
                'storage_gb': self._calculate_storage_requirements(image_info),
                'gpu_required': image_info.gpu_required,
                'privileged_required': image_info.privileged_required
            },
            'optimization_suggestions': await self._generate_optimization_suggestions(image_info)
        }
        
        return recommendations
    
    async def _generate_optimization_suggestions(self, image_info: DockerImageInfo) -> List[str]:
        """Generate optimization suggestions"""
        suggestions = []
        
        if image_info.size_mb > 1000:
            suggestions.append("Consider using a smaller base image (e.g., Alpine) to reduce size")
        
        if image_info.privileged_required:
            suggestions.append("Review if privileged access is truly needed for security")
        
        if len(image_info.volumes) > 5:
            suggestions.append("Consider consolidating volumes to reduce complexity")
        
        if image_info.gpu_required and not image_info.cuda_version:
            suggestions.append("Specify CUDA version for better GPU optimization")
        
        if image_info.base_os == 'unknown':
            suggestions.append("Use a well-known base image for better optimization")
        
        return suggestions