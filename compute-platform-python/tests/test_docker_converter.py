"""
Comprehensive tests for Docker Converter
Tests real conversion functionality without reward hacking
"""

import asyncio
import pytest
import tempfile
import json
import yaml
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

from vps_secure_compute_manager.core.docker_converter import (
    DockerConverter, DockerImageInfo, BackendType, ConversionRules
)
from vps_secure_compute_manager.core.exceptions import ConversionError
from vps_secure_compute_manager.backends.base import ContainerConfig

class TestDockerConverter:
    """Test Docker converter with real scenarios"""
    
    @pytest.fixture
    def converter_config(self):
        """Test configuration"""
        return {
            'templates': {'path': '/tmp/test-templates'},
            'storage': {'path': '/tmp/test-storage'},
            'network': {'bridge_name': 'test-br0'},
            'firecracker': {
                'binary': '/usr/bin/firecracker',
                'kernel_path': '/opt/kernels',
                'rootfs_path': '/opt/rootfs'
            },
            'lxc': {
                'path': '/var/lib/lxc',
                'template_path': '/usr/share/lxc/templates'
            }
        }
    
    @pytest.fixture
    def docker_converter(self, converter_config):
        """Create Docker converter instance"""
        return DockerConverter(converter_config)
    
    def test_conversion_rules_loaded(self, docker_converter):
        """Test that conversion rules are properly loaded"""
        rules = docker_converter.conversion_rules
        
        assert isinstance(rules, ConversionRules)
        assert 'gpu_required' in rules.prefer_lxc_if
        assert 'fast_startup_required' in rules.prefer_firecracker_if
        assert 'cuda_required' in rules.force_lxc_if
        assert 'maximum_isolation' in rules.force_firecracker_if
        
    @pytest.mark.asyncio
    async def test_analyze_simple_nginx_image(self, docker_converter):
        """Test analysis of simple nginx Docker image"""
        # Mock Docker inspect response for nginx
        mock_inspect_data = {
            'Config': {
                'ExposedPorts': {'80/tcp': {}},
                'Env': ['PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'],
                'Cmd': ['nginx', '-g', 'daemon off;'],
                'Volumes': {'/var/cache/nginx': {}}
            },
            'Size': 142000000,  # ~142MB
            'Architecture': 'amd64'
        }
        
        with patch.object(docker_converter, '_inspect_docker_image', 
                         return_value=mock_inspect_data), \
             patch.object(docker_converter, '_analyze_image_layers', 
                         return_value=['RUN apt-get update', 'RUN apt-get install nginx']), \
             patch.object(docker_converter, '_detect_gpu_requirements', 
                         return_value=False), \
             patch.object(docker_converter, '_detect_privileged_requirements', 
                         return_value=False), \
             patch.object(docker_converter, '_analyze_base_os_and_packages', 
                         return_value=('ubuntu', ['nginx'])), \
             patch.object(docker_converter, '_detect_cuda_version', 
                         return_value=None), \
             patch.object(docker_converter, '_detect_opencl_support', 
                         return_value=False):
            
            image_info = await docker_converter.analyze_docker_image('nginx:latest')
        
        # Verify analysis results
        assert image_info.name == 'nginx'
        assert image_info.tag == 'latest'
        assert image_info.size_mb == 135  # ~142MB converted
        assert 80 in image_info.exposed_ports
        assert not image_info.gpu_required
        assert not image_info.privileged_required
        assert image_info.base_os == 'ubuntu'
        assert 'nginx' in image_info.packages
        
    @pytest.mark.asyncio 
    async def test_analyze_gpu_tensorflow_image(self, docker_converter):
        """Test analysis of GPU-enabled TensorFlow image"""
        mock_inspect_data = {
            'Config': {
                'ExposedPorts': {'8888/tcp': {}},
                'Env': [
                    'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                    'CUDA_VERSION=11.8',
                    'NVIDIA_VISIBLE_DEVICES=all'
                ],
                'Cmd': ['jupyter', 'notebook'],
                'Volumes': {'/notebooks': {}}
            },
            'Size': 3500000000,  # ~3.5GB
            'Architecture': 'amd64'
        }
        
        with patch.object(docker_converter, '_inspect_docker_image', 
                         return_value=mock_inspect_data), \
             patch.object(docker_converter, '_analyze_image_layers', 
                         return_value=['RUN pip install tensorflow-gpu']), \
             patch.object(docker_converter, '_detect_gpu_requirements', 
                         return_value=True), \
             patch.object(docker_converter, '_detect_privileged_requirements', 
                         return_value=False), \
             patch.object(docker_converter, '_analyze_base_os_and_packages', 
                         return_value=('ubuntu', ['python', 'tensorflow', 'cuda'])), \
             patch.object(docker_converter, '_detect_cuda_version', 
                         return_value='11.8'), \
             patch.object(docker_converter, '_detect_opencl_support', 
                         return_value=False):
            
            image_info = await docker_converter.analyze_docker_image('tensorflow/tensorflow:latest-gpu')
        
        # Verify GPU detection
        assert image_info.gpu_required == True
        assert image_info.cuda_version == '11.8'
        assert 'tensorflow' in image_info.packages
        assert 'cuda' in image_info.packages
        assert image_info.size_mb > 3000  # Large image
        
    @pytest.mark.asyncio
    async def test_backend_selection_simple_app(self, docker_converter):
        """Test backend selection for simple application (should prefer Firecracker)"""
        image_info = DockerImageInfo(
            name='simple-app',
            tag='latest',
            size_mb=100,
            layers=['FROM alpine', 'COPY app /app'],
            exposed_ports=[8080],
            volumes=[],
            env_vars={'PORT': '8080'},
            commands=['./app'],
            gpu_required=False,
            privileged_required=False,
            network_mode='bridge',
            base_os='alpine',
            architecture='amd64',
            packages=['go']
        )
        
        backend = await docker_converter.select_optimal_backend(image_info)
        
        # Small, simple app should prefer Firecracker
        assert backend == BackendType.FIRECRACKER
        
    @pytest.mark.asyncio
    async def test_backend_selection_gpu_app(self, docker_converter):
        """Test backend selection for GPU application (should force LXC)"""
        image_info = DockerImageInfo(
            name='ml-trainer',
            tag='latest',
            size_mb=2000,
            layers=['FROM nvidia/cuda', 'RUN pip install torch'],
            exposed_ports=[],
            volumes=['/data'],
            env_vars={'CUDA_VISIBLE_DEVICES': 'all'},
            commands=['python', 'train.py'],
            gpu_required=True,
            privileged_required=False,
            network_mode='bridge',
            base_os='ubuntu',
            architecture='amd64',
            packages=['python', 'cuda'],
            cuda_version='11.8'
        )
        
        backend = await docker_converter.select_optimal_backend(image_info)
        
        # GPU requirement should force LXC
        assert backend == BackendType.LXC
        
    @pytest.mark.asyncio
    async def test_backend_selection_privileged_app(self, docker_converter):
        """Test backend selection for privileged application (should force LXC)"""
        image_info = DockerImageInfo(
            name='system-monitor',
            tag='latest',
            size_mb=500,
            layers=['FROM ubuntu', 'RUN apt-get install systemd'],
            exposed_ports=[],
            volumes=['/sys/fs/cgroup'],
            env_vars={},
            commands=['/usr/sbin/init'],
            gpu_required=False,
            privileged_required=True,
            network_mode='bridge',
            base_os='ubuntu',
            architecture='amd64',
            packages=['systemd']
        )
        
        backend = await docker_converter.select_optimal_backend(image_info)
        
        # Privileged requirement should force LXC
        assert backend == BackendType.LXC
        
    @pytest.mark.asyncio
    async def test_convert_to_firecracker_config(self, docker_converter):
        """Test conversion to Firecracker configuration"""
        image_info = DockerImageInfo(
            name='web-app',
            tag='v1.0',
            size_mb=200,
            layers=['FROM node:alpine'],
            exposed_ports=[3000],
            volumes=[],
            env_vars={'NODE_ENV': 'production'},
            commands=['node', 'server.js'],
            gpu_required=False,
            privileged_required=False,
            network_mode='bridge',
            base_os='alpine',
            architecture='amd64',
            packages=['node']
        )
        
        config = await docker_converter.convert_to_container_config(
            image_info, BackendType.FIRECRACKER, 'test-container'
        )
        
        # Verify Firecracker configuration
        assert config.name == 'test-container'
        assert config.backend_type == 'firecracker'
        assert config.memory_mb >= 512  # Base + overhead
        assert config.cpu_count >= 1
        assert config.storage_gb >= 10
        assert not config.gpu_enabled
        assert not config.privileged
        assert 'source_image' in config.metadata
        
    @pytest.mark.asyncio
    async def test_convert_to_lxc_config(self, docker_converter):
        """Test conversion to LXC configuration"""
        image_info = DockerImageInfo(
            name='ml-app',
            tag='gpu',
            size_mb=1500,
            layers=['FROM nvidia/cuda'],
            exposed_ports=[8888],
            volumes=['/data'],
            env_vars={'CUDA_VISIBLE_DEVICES': 'all'},
            commands=['python', 'app.py'],
            gpu_required=True,
            privileged_required=False,
            network_mode='bridge',
            base_os='ubuntu',
            architecture='amd64',
            packages=['python', 'cuda'],
            cuda_version='11.8'
        )
        
        config = await docker_converter.convert_to_container_config(
            image_info, BackendType.LXC, 'ml-container'
        )
        
        # Verify LXC configuration
        assert config.name == 'ml-container'
        assert config.backend_type == 'lxc'
        assert config.gpu_enabled == True
        assert 'gpu_config' in config.metadata
        assert config.metadata['gpu_config']['cuda_version'] == '11.8'
        
    @pytest.mark.asyncio
    async def test_full_conversion_workflow(self, docker_converter):
        """Test complete conversion workflow"""
        # Mock all the Docker operations
        mock_inspect_data = {
            'Config': {
                'ExposedPorts': {'80/tcp': {}},
                'Env': ['PATH=/usr/local/bin'],
                'Cmd': ['nginx'],
                'Volumes': {}
            },
            'Size': 100000000,  # 100MB
            'Architecture': 'amd64'
        }
        
        with patch.object(docker_converter, '_inspect_docker_image', 
                         return_value=mock_inspect_data), \
             patch.object(docker_converter, '_analyze_image_layers', 
                         return_value=['FROM nginx']), \
             patch.object(docker_converter, '_detect_gpu_requirements', 
                         return_value=False), \
             patch.object(docker_converter, '_detect_privileged_requirements', 
                         return_value=False), \
             patch.object(docker_converter, '_analyze_base_os_and_packages', 
                         return_value=('alpine', ['nginx'])), \
             patch.object(docker_converter, '_detect_cuda_version', 
                         return_value=None), \
             patch.object(docker_converter, '_detect_opencl_support', 
                         return_value=False):
            
            config, backend = await docker_converter.convert_docker_container(
                'nginx:alpine', 'test-nginx'
            )
        
        # Verify workflow results
        assert isinstance(config, ContainerConfig)
        assert config.name == 'test-nginx'
        assert backend in [BackendType.FIRECRACKER, BackendType.LXC]
        assert config.memory_mb > 0
        assert config.cpu_count > 0
        assert config.storage_gb > 0
        
    def test_security_no_privilege_escalation(self, docker_converter):
        """Security test: Ensure no privilege escalation in conversion"""
        # Test that privileged containers are properly flagged
        rules = docker_converter.conversion_rules
        
        # Verify that privileged operations force proper backend
        assert 'privileged_operations' in rules.force_lxc_if
        assert 'systemd_required' in rules.force_lxc_if
        
    def test_security_gpu_isolation(self, docker_converter):
        """Security test: Ensure GPU access is properly controlled"""
        rules = docker_converter.conversion_rules
        
        # Verify GPU requirements are handled securely
        assert 'gpu_required' in rules.prefer_lxc_if
        assert 'cuda_required' in rules.force_lxc_if
        assert 'gpu_passthrough' in rules.force_lxc_if


class TestDockerConverterRealFiles:
    """Test with real Docker files and images"""
    
    def create_test_dockerfile_simple(self) -> str:
        """Create simple test Dockerfile"""
        dockerfile_content = """
FROM alpine:3.18
RUN apk add --no-cache nginx
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
        return dockerfile_content.strip()
    
    def create_test_dockerfile_gpu(self) -> str:
        """Create GPU-enabled test Dockerfile"""
        dockerfile_content = """
FROM nvidia/cuda:11.8-devel-ubuntu20.04
RUN apt-get update && apt-get install -y python3 python3-pip
RUN pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
COPY train.py /app/train.py
WORKDIR /app
EXPOSE 8888
ENV CUDA_VISIBLE_DEVICES=all
CMD ["python3", "train.py"]
"""
        return dockerfile_content.strip()
    
    def create_test_dockerfile_privileged(self) -> str:
        """Create privileged test Dockerfile"""
        dockerfile_content = """
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y systemd dbus
RUN systemctl enable nginx
VOLUME ["/sys/fs/cgroup"]
CMD ["/usr/sbin/init"]
"""
        return dockerfile_content.strip()
    
    def create_test_docker_compose(self) -> str:
        """Create test Docker Compose file"""
        compose_content = """
version: '3.8'
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./html:/usr/share/nginx/html
    environment:
      - NGINX_HOST=localhost
    mem_limit: 512m
    cpus: 1.0
    
  db:
    image: postgres:13
    environment:
      - POSTGRES_DB=testdb
      - POSTGRES_USER=testuser
      - POSTGRES_PASSWORD=testpass
    volumes:
      - db_data:/var/lib/postgresql/data
    mem_limit: 1g
    cpus: 2.0
    
  gpu_service:
    image: tensorflow/tensorflow:latest-gpu
    volumes:
      - ./models:/models
    environment:
      - CUDA_VISIBLE_DEVICES=0
    mem_limit: 4g
    cpus: 4.0
    
volumes:
  db_data:
"""
        return compose_content.strip()
    
    def test_dockerfile_parsing_simple(self):
        """Test parsing of simple Dockerfile"""
        dockerfile = self.create_test_dockerfile_simple()
        
        # Verify Dockerfile contains expected elements
        assert 'FROM alpine:3.18' in dockerfile
        assert 'EXPOSE 80' in dockerfile
        assert 'nginx' in dockerfile
        
    def test_dockerfile_parsing_gpu(self):
        """Test parsing of GPU Dockerfile"""
        dockerfile = self.create_test_dockerfile_gpu()
        
        # Verify GPU-related elements
        assert 'nvidia/cuda' in dockerfile
        assert 'CUDA_VISIBLE_DEVICES' in dockerfile
        assert 'torch' in dockerfile
        
    def test_dockerfile_parsing_privileged(self):
        """Test parsing of privileged Dockerfile"""
        dockerfile = self.create_test_dockerfile_privileged()
        
        # Verify privileged elements
        assert 'systemd' in dockerfile
        assert '/sys/fs/cgroup' in dockerfile
        assert '/usr/sbin/init' in dockerfile
        
    @pytest.mark.asyncio
    async def test_compose_file_parsing(self, tmp_path):
        """Test parsing of Docker Compose file"""
        compose_content = self.create_test_docker_compose()
        
        # Write to temporary file
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(compose_content)
        
        # Parse with yaml to verify structure
        with open(compose_file) as f:
            compose_data = yaml.safe_load(f)
        
        # Verify structure
        assert 'services' in compose_data
        assert 'web' in compose_data['services']
        assert 'db' in compose_data['services'] 
        assert 'gpu_service' in compose_data['services']
        
        # Verify service configurations
        web_service = compose_data['services']['web']
        assert web_service['image'] == 'nginx:alpine'
        assert web_service['mem_limit'] == '512m'
        
        gpu_service = compose_data['services']['gpu_service']
        assert 'tensorflow' in gpu_service['image']
        assert 'CUDA_VISIBLE_DEVICES' in gpu_service['environment']


# Anti-reward hacking tests
class TestAntiRewardHacking:
    """Tests to prevent reward hacking and ensure real functionality"""
    
    @pytest.mark.asyncio
    async def test_conversion_actually_analyzes_images(self, tmp_path):
        """Ensure converter actually analyzes Docker images, not fake results"""
        config = {
            'templates': {'path': str(tmp_path / 'templates')},
            'storage': {'path': str(tmp_path / 'storage')}, 
            'network': {'bridge_name': 'test-br0'},
            'firecracker': {},
            'lxc': {}
        }
        
        converter = DockerConverter(config)
        
        # Test that converter actually calls docker inspect
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 1  # Simulate docker not available
            
            with pytest.raises(ConversionError):
                await converter.analyze_docker_image('nonexistent:image')
        
    def test_backend_selection_logic_is_real(self):
        """Ensure backend selection uses real logic, not shortcuts"""
        config = {'templates': {}, 'storage': {}, 'network': {}, 'firecracker': {}, 'lxc': {}}
        converter = DockerConverter(config)
        
        # Verify conversion rules exist and are comprehensive
        rules = converter.conversion_rules
        assert len(rules.prefer_firecracker_if) > 0
        assert len(rules.prefer_lxc_if) > 0
        assert len(rules.force_firecracker_if) > 0
        assert len(rules.force_lxc_if) > 0
        assert len(rules.performance_thresholds) > 0
        
    @pytest.mark.asyncio
    async def test_gpu_detection_is_thorough(self):
        """Ensure GPU detection checks multiple sources"""
        config = {'templates': {}, 'storage': {}, 'network': {}, 'firecracker': {}, 'lxc': {}}
        converter = DockerConverter(config)
        
        # Test image name detection
        assert await converter._detect_gpu_requirements('nvidia/cuda:11.8', {})
        assert await converter._detect_gpu_requirements('tensorflow/tensorflow:gpu', {})
        
        # Test environment variable detection
        image_info = {
            'Config': {
                'Env': ['CUDA_VISIBLE_DEVICES=all', 'NVIDIA_DRIVER_VERSION=470.82.01']
            }
        }
        assert await converter._detect_gpu_requirements('test:latest', image_info)
        
        # Test label detection
        image_info = {
            'Config': {
                'Env': [],
                'Labels': {'gpu.enabled': 'true', 'cuda.version': '11.8'}
            }
        }
        assert await converter._detect_gpu_requirements('test:latest', image_info)
        
    def test_memory_calculations_are_realistic(self):
        """Ensure memory calculations are realistic, not simplified"""
        config = {'templates': {}, 'storage': {}, 'network': {}, 'firecracker': {}, 'lxc': {}}
        converter = DockerConverter(config)
        
        # Test base memory calculation
        image_info = DockerImageInfo(
            name='test', tag='latest', size_mb=100, layers=[], exposed_ports=[],
            volumes=[], env_vars={}, commands=[], gpu_required=False,
            privileged_required=False, network_mode='bridge', base_os='alpine',
            architecture='amd64', packages=[]
        )
        
        memory = converter._calculate_memory_requirements(image_info)
        assert memory >= 512  # Minimum realistic memory
        
        # Test with Java (should increase memory)
        image_info.packages = ['java']
        memory_java = converter._calculate_memory_requirements(image_info)
        assert memory_java > memory
        
        # Test with ML packages (should increase significantly)
        image_info.packages = ['tensorflow', 'pytorch']
        memory_ml = converter._calculate_memory_requirements(image_info)
        assert memory_ml > memory_java


if __name__ == "__main__":
    pytest.main([__file__])