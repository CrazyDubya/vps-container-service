"""
Main CLI entry point for VPS Secure Compute Manager
"""

import click
import asyncio
import json
import sys
from typing import Dict, Any

from ..core.database import DatabaseManager
from ..core.exceptions import VPSSecureComputeError
from ..iam.auth import AuthenticationManager
from ..backends.firecracker import FirecrackerBackend
from ..backends.lxc import LXCBackend

# Global context for CLI
cli_context = {}

@click.group()
@click.option('--config', default='/etc/vps-secure-compute/config.yaml', 
              help='Configuration file path')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.pass_context
def main(ctx, config, debug):
    """VPS Secure Compute Manager - Multi-tenant secure containers"""
    ctx.ensure_object(dict)
    ctx.obj['config_file'] = config
    ctx.obj['debug'] = debug
    
    # Initialize logging
    import logging
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

@main.command()
@click.option('--email', prompt=True, help='Email address')
@click.option('--password', prompt=True, hide_input=True, help='Password')
@click.option('--save-token', is_flag=True, help='Save authentication token')
@click.pass_context
def login(ctx, email, password, save_token):
    """Login to VPS Secure Compute Manager"""
    try:
        # Initialize authentication manager
        auth_manager = AuthenticationManager("your-jwt-secret-key")
        
        # Initialize database (would load from config in production)
        db_manager = DatabaseManager("sqlite:///vps_secure.db")
        
        with db_manager.get_session() as session:
            # Authenticate user
            auth_result = auth_manager.authenticate_user(
                session, email, password
            )
            
            click.echo(f"✅ Successfully logged in as {auth_result['email']}")
            click.echo(f"🏢 Tenant: {auth_result['tenant_id']}")
            click.echo(f"👤 Role: {auth_result['role']}")
            
            if save_token:
                # Save token to config file (simplified)
                token_file = click.get_app_dir('vps-secure-compute') + '/token'
                import os
                os.makedirs(os.path.dirname(token_file), exist_ok=True)
                with open(token_file, 'w') as f:
                    f.write(auth_result['jwt_token'])
                click.echo(f"💾 Token saved to {token_file}")
            
    except VPSSecureComputeError as e:
        click.echo(f"❌ Login failed: {e.message}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {str(e)}", err=True)
        sys.exit(1)

@main.command()
@click.pass_context
def logout(ctx):
    """Logout from VPS Secure Compute Manager"""
    try:
        # Remove saved token
        token_file = click.get_app_dir('vps-secure-compute') + '/token'
        import os
        if os.path.exists(token_file):
            os.remove(token_file)
            click.echo("✅ Successfully logged out")
        else:
            click.echo("ℹ️  No active session found")
    except Exception as e:
        click.echo(f"❌ Logout error: {str(e)}", err=True)

@main.group()
def container():
    """Container management commands"""
    pass

@container.command('list')
@click.option('--backend', type=click.Choice(['firecracker', 'lxc', 'all']), 
              default='all', help='Backend type filter')
@click.option('--status', help='Status filter')
@click.option('--format', type=click.Choice(['table', 'json']), 
              default='table', help='Output format')
def list_containers(backend, status, format):
    """List containers"""
    try:
        # Get user context (would load from saved token in production)
        user_context = _get_user_context()
        
        # Initialize backends
        backends = []
        if backend in ['firecracker', 'all']:
            backends.append(('firecracker', FirecrackerBackend()))
        if backend in ['lxc', 'all']:
            backends.append(('lxc', LXCBackend()))
        
        # Collect containers from all backends
        all_containers = []
        for backend_name, backend_impl in backends:
            try:
                containers = asyncio.run(backend_impl.list_containers(
                    tenant_id=user_context['tenant_id'],
                    user_id=user_context['user_id']
                ))
                all_containers.extend(containers)
            except Exception as e:
                click.echo(f"⚠️  Warning: Failed to list {backend_name} containers: {str(e)}", err=True)
        
        # Filter by status if specified
        if status:
            all_containers = [c for c in all_containers if c.status.value == status]
        
        # Output results
        if format == 'json':
            container_data = []
            for container in all_containers:
                container_data.append({
                    'id': container.id,
                    'name': container.name,
                    'status': container.status.value,
                    'backend': container.backend_type,
                    'memory_mb': container.memory_mb,
                    'cpu_count': container.cpu_count,
                    'gpu_count': container.gpu_count,
                    'ip_address': container.ip_address,
                    'created_at': container.created_at
                })
            click.echo(json.dumps(container_data, indent=2))
        else:
            # Table format
            if not all_containers:
                click.echo("No containers found")
                return
            
            # Header
            click.echo(f"{'ID':<12} {'Name':<20} {'Status':<10} {'Backend':<12} {'Memory':<8} {'CPU':<4} {'GPU':<4} {'IP Address':<15} {'Created':<20}")
            click.echo("-" * 120)
            
            # Rows
            for container in all_containers:
                click.echo(f"{container.id[:8]:<12} {container.name:<20} {container.status.value:<10} "
                          f"{container.backend_type:<12} {container.memory_mb:<8} {container.cpu_count:<4} "
                          f"{container.gpu_count:<4} {container.ip_address or 'N/A':<15} {container.created_at:<20}")
    
    except Exception as e:
        click.echo(f"❌ Failed to list containers: {str(e)}", err=True)
        sys.exit(1)

@container.command('create')
@click.option('--name', required=True, help='Container name')
@click.option('--template', required=True, help='Template name')
@click.option('--backend', type=click.Choice(['firecracker', 'lxc']), 
              required=True, help='Backend type')
@click.option('--memory', type=int, default=512, help='Memory in MB')
@click.option('--cpu', type=int, default=1, help='CPU count')
@click.option('--storage', type=float, default=10.0, help='Storage in GB')
@click.option('--gpu', type=int, default=0, help='GPU count (LXC only)')
@click.option('--start', is_flag=True, help='Start container after creation')
def create_container(name, template, backend, memory, cpu, storage, gpu, start):
    """Create a new container"""
    try:
        # Get user context
        user_context = _get_user_context()
        
        # Initialize backend
        if backend == 'firecracker':
            backend_impl = FirecrackerBackend()
            if gpu > 0:
                click.echo("⚠️  Warning: Firecracker doesn't support GPU, setting GPU count to 0")
                gpu = 0
        else:
            backend_impl = LXCBackend()
        
        # Create container config
        from ..backends.base import ContainerConfig
        config = ContainerConfig(
            name=name,
            template=template,
            memory_mb=memory,
            cpu_count=cpu,
            storage_gb=storage,
            gpu_count=gpu,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=user_context
        )
        
        # Create container
        click.echo(f"🚀 Creating {backend} container '{name}'...")
        container_id = asyncio.run(backend_impl.create_container(config))
        
        click.echo(f"✅ Container created successfully")
        click.echo(f"🆔 Container ID: {container_id}")
        
        # Start container if requested
        if start:
            click.echo(f"▶️  Starting container...")
            success = asyncio.run(backend_impl.start_container(container_id))
            if success:
                click.echo(f"✅ Container started successfully")
            else:
                click.echo(f"❌ Failed to start container", err=True)
    
    except Exception as e:
        click.echo(f"❌ Failed to create container: {str(e)}", err=True)
        sys.exit(1)

@container.command('start')
@click.argument('container_id')
def start_container(container_id):
    """Start a container"""
    try:
        # Find container and start it
        backends = [FirecrackerBackend(), LXCBackend()]
        
        for backend in backends:
            try:
                success = asyncio.run(backend.start_container(container_id))
                if success:
                    click.echo(f"✅ Container {container_id} started successfully")
                    return
            except Exception:
                continue
        
        click.echo(f"❌ Container {container_id} not found", err=True)
        sys.exit(1)
    
    except Exception as e:
        click.echo(f"❌ Failed to start container: {str(e)}", err=True)
        sys.exit(1)

@container.command('stop')
@click.argument('container_id')
@click.option('--force', is_flag=True, help='Force stop container')
def stop_container(container_id, force):
    """Stop a container"""
    try:
        # Find container and stop it
        backends = [FirecrackerBackend(), LXCBackend()]
        
        for backend in backends:
            try:
                success = asyncio.run(backend.stop_container(container_id, force=force))
                if success:
                    click.echo(f"✅ Container {container_id} stopped successfully")
                    return
            except Exception:
                continue
        
        click.echo(f"❌ Container {container_id} not found", err=True)
        sys.exit(1)
    
    except Exception as e:
        click.echo(f"❌ Failed to stop container: {str(e)}", err=True)
        sys.exit(1)

@container.command('exec')
@click.argument('container_id')
@click.argument('command', nargs=-1)
@click.option('--timeout', type=int, default=30, help='Command timeout in seconds')
def exec_container(container_id, command, timeout):
    """Execute command in container"""
    try:
        if not command:
            click.echo("❌ No command specified", err=True)
            sys.exit(1)
        
        # Find container and execute command
        backends = [FirecrackerBackend(), LXCBackend()]
        
        for backend in backends:
            try:
                result = asyncio.run(backend.exec_command(
                    container_id, list(command), timeout=timeout
                ))
                
                # Output results
                if result.stdout:
                    click.echo(result.stdout)
                if result.stderr:
                    click.echo(result.stderr, err=True)
                
                sys.exit(result.exit_code)
                
            except Exception:
                continue
        
        click.echo(f"❌ Container {container_id} not found", err=True)
        sys.exit(1)
    
    except Exception as e:
        click.echo(f"❌ Failed to execute command: {str(e)}", err=True)
        sys.exit(1)

@main.command('templates')
@click.option('--backend', type=click.Choice(['firecracker', 'lxc', 'all']), 
              default='all', help='Backend type filter')
def list_templates(backend):
    """List available templates"""
    try:
        # Initialize backends
        backends = []
        if backend in ['firecracker', 'all']:
            backends.append(('firecracker', FirecrackerBackend()))
        if backend in ['lxc', 'all']:
            backends.append(('lxc', LXCBackend()))
        
        # Collect templates from all backends
        click.echo("Available Templates:")
        click.echo("=" * 60)
        
        for backend_name, backend_impl in backends:
            try:
                templates = backend_impl.get_supported_templates()
                if templates:
                    click.echo(f"\n{backend_name.upper()} Templates:")
                    for template in templates:
                        gpu_support = "✅" if template.get('gpu_support', False) else "❌"
                        click.echo(f"  📦 {template['name']:<20} {template['description']:<40} GPU: {gpu_support}")
            except Exception as e:
                click.echo(f"⚠️  Warning: Failed to list {backend_name} templates: {str(e)}", err=True)
    
    except Exception as e:
        click.echo(f"❌ Failed to list templates: {str(e)}", err=True)
        sys.exit(1)

# Docker conversion commands
@main.group()
def docker():
    """Docker conversion commands"""
    pass

@docker.command()
@click.argument('image_name')
@click.option('--format', type=click.Choice(['json', 'table']), default='table', 
              help='Output format')
@click.pass_context
def analyze(ctx, image_name, format):
    """Analyze Docker image and get conversion recommendations"""
    try:
        from ..core.docker_converter import DockerConverter
        import yaml
        
        # Load configuration
        with open(ctx.obj['config_file']) as f:
            config = yaml.safe_load(f)
        
        # Create converter
        converter = DockerConverter(config)
        
        # Run analysis
        async def run_analysis():
            recommendations = await converter.get_conversion_recommendations(image_name)
            
            if format == 'json':
                click.echo(json.dumps(recommendations, indent=2))
            else:
                # Table format
                image_info = recommendations['image_analysis']
                click.echo(f"\n🔍 Docker Image Analysis: {image_name}")
                click.echo("=" * 60)
                click.echo(f"📊 Size: {image_info['size_mb']} MB")
                click.echo(f"🏗️  Base OS: {image_info['base_os']}")
                click.echo(f"🔧 Architecture: {image_info['architecture']}")
                click.echo(f"🚪 Exposed Ports: {', '.join(map(str, image_info['exposed_ports']))}")
                click.echo(f"💾 Volumes: {len(image_info['volumes'])}")
                click.echo(f"🎮 GPU Required: {'Yes' if image_info['gpu_required'] else 'No'}")
                click.echo(f"🔐 Privileged: {'Yes' if image_info['privileged_required'] else 'No'}")
                
                if image_info['cuda_version']:
                    click.echo(f"🏗️  CUDA Version: {image_info['cuda_version']}")
                
                click.echo(f"\n📦 Packages: {', '.join(image_info['packages'])}")
                
                click.echo(f"\n🎯 Recommended Backend: {recommendations['recommended_backend'].upper()}")
                
                scores = recommendations['backend_scores']
                click.echo(f"\n📊 Backend Scores:")
                click.echo(f"  🔥 Firecracker: {scores['firecracker']}/100")
                click.echo(f"  📦 LXC: {scores['lxc']}/100")
                
                click.echo(f"\n💡 Optimization Suggestions:")
                for suggestion in recommendations['optimization_suggestions']:
                    click.echo(f"  • {suggestion}")
                
                requirements = recommendations['requirements']
                click.echo(f"\n📋 Resource Requirements:")
                click.echo(f"  💾 Memory: {requirements['memory_mb']} MB")
                click.echo(f"  🔧 CPU: {requirements['cpu_count']} cores")
                click.echo(f"  💽 Storage: {requirements['storage_gb']} GB")
        
        asyncio.run(run_analysis())
        
    except Exception as e:
        click.echo(f"❌ Failed to analyze Docker image: {str(e)}", err=True)
        sys.exit(1)

@docker.command()
@click.argument('image_name')
@click.argument('container_name')
@click.option('--backend', type=click.Choice(['auto', 'firecracker', 'lxc']), 
              default='auto', help='Preferred backend')
@click.option('--memory', type=int, help='Memory override in MB')
@click.option('--cpu', type=int, help='CPU override count')
@click.option('--storage', type=float, help='Storage override in GB')
@click.option('--gpu', is_flag=True, help='Force GPU support')
@click.option('--privileged', is_flag=True, help='Force privileged mode')
@click.option('--dry-run', is_flag=True, help='Show conversion plan without creating')
@click.pass_context
def convert(ctx, image_name, container_name, backend, memory, cpu, storage, 
            gpu, privileged, dry_run):
    """Convert Docker container to native format"""
    try:
        from ..core.docker_converter import DockerConverter, BackendType
        import yaml
        
        # Get user context
        user_ctx = _get_user_context()
        
        # Load configuration
        with open(ctx.obj['config_file']) as f:
            config = yaml.safe_load(f)
        
        # Create converter
        converter = DockerConverter(config)
        
        # Build user overrides
        user_overrides = {}
        if memory:
            user_overrides['memory_mb'] = memory
        if cpu:
            user_overrides['cpu_count'] = cpu  
        if storage:
            user_overrides['storage_gb'] = storage
        if gpu:
            user_overrides['gpu_enabled'] = True
        if privileged:
            user_overrides['privileged'] = True
        
        # Map backend preference
        backend_map = {
            'auto': BackendType.AUTO,
            'firecracker': BackendType.FIRECRACKER,
            'lxc': BackendType.LXC
        }
        backend_preference = backend_map[backend]
        
        async def run_conversion():
            if dry_run:
                # Show conversion plan
                config_obj, selected_backend = await converter.convert_docker_container(
                    image_name, container_name, backend_preference, 
                    None, user_overrides
                )
                
                click.echo(f"\n🎯 Conversion Plan for {image_name} -> {container_name}")
                click.echo("=" * 60)
                click.echo(f"Selected Backend: {selected_backend.value.upper()}")
                click.echo(f"Memory: {config_obj.memory_mb} MB")
                click.echo(f"CPU: {config_obj.cpu_count} cores")
                click.echo(f"Storage: {config_obj.storage_gb} GB")
                click.echo(f"GPU Enabled: {config_obj.gpu_enabled}")
                click.echo(f"Privileged: {config_obj.privileged}")
                click.echo(f"Template: {config_obj.template}")
                click.echo(f"Network Mode: {config_obj.network_mode}")
                click.echo("\n💡 Run without --dry-run to create the container")
                
            else:
                # Actually create container
                click.echo(f"🔄 Converting Docker container: {image_name} -> {container_name}")
                
                container_id = await converter.create_converted_container(
                    image_name, container_name, backend_preference,
                    None, user_overrides
                )
                
                click.echo(f"✅ Container created successfully!")
                click.echo(f"📋 Container ID: {container_id}")
                click.echo(f"📦 Container Name: {container_name}")
                click.echo(f"\n🚀 Next steps:")
                click.echo(f"  vps-secure start-container {container_name}")
                click.echo(f"  vps-secure list-containers")
        
        asyncio.run(run_conversion())
        
    except Exception as e:
        click.echo(f"❌ Failed to convert Docker container: {str(e)}", err=True)
        sys.exit(1)

@docker.command()
@click.argument('compose_file', type=click.Path(exists=True))
@click.option('--project-name', default='converted-project', 
              help='Project name for converted containers')
@click.option('--dry-run', is_flag=True, help='Show conversion plan without creating')
@click.pass_context
def compose(ctx, compose_file, project_name, dry_run):
    """Convert Docker Compose file to native containers"""
    try:
        from ..core.docker_converter import DockerConverter
        import yaml
        
        # Get user context
        user_ctx = _get_user_context()
        
        # Load configuration
        with open(ctx.obj['config_file']) as f:
            config = yaml.safe_load(f)
        
        # Create converter
        converter = DockerConverter(config)
        
        async def run_compose_conversion():
            click.echo(f"🔄 Converting Docker Compose file: {compose_file}")
            
            converted_services = await converter.batch_convert_compose_file(compose_file)
            
            click.echo(f"\n📋 Conversion Summary")
            click.echo("=" * 50)
            click.echo(f"Total Services: {len(converted_services)}")
            
            # Count backends
            backend_count = {'firecracker': 0, 'lxc': 0}
            for service_name, (config_obj, backend) in converted_services.items():
                backend_count[backend.value] += 1
            
            click.echo(f"Firecracker: {backend_count['firecracker']}")
            click.echo(f"LXC: {backend_count['lxc']}")
            
            click.echo(f"\n📦 Service Details:")
            for service_name, (config_obj, backend) in converted_services.items():
                click.echo(f"\n  🔹 {service_name}")
                click.echo(f"    Backend: {backend.value.upper()}")
                click.echo(f"    Memory: {config_obj.memory_mb} MB")
                click.echo(f"    CPU: {config_obj.cpu_count} cores")
                click.echo(f"    Storage: {config_obj.storage_gb} GB")
                click.echo(f"    GPU: {config_obj.gpu_enabled}")
                click.echo(f"    Privileged: {config_obj.privileged}")
            
            if not dry_run:
                click.echo(f"\n🚀 Creating containers...")
                created_containers = []
                
                for service_name, (config_obj, backend) in converted_services.items():
                    try:
                        if backend.value == 'firecracker':
                            container_id = await converter.firecracker_backend.create_container(config_obj)
                        else:
                            container_id = await converter.lxc_backend.create_container(config_obj)
                        
                        created_containers.append((service_name, container_id))
                        click.echo(f"  ✅ Created {service_name}: {container_id}")
                        
                    except Exception as e:
                        click.echo(f"  ❌ Failed to create {service_name}: {str(e)}", err=True)
                
                click.echo(f"\n✅ Created {len(created_containers)} containers successfully!")
                click.echo(f"💡 Use 'vps-secure list-containers' to see all containers")
            else:
                click.echo(f"\n💡 Run without --dry-run to create the containers")
        
        asyncio.run(run_compose_conversion())
        
    except Exception as e:
        click.echo(f"❌ Failed to convert Docker Compose: {str(e)}", err=True)
        sys.exit(1)

@docker.command()
@click.pass_context
def backends(ctx):
    """Show available conversion backends and their capabilities"""
    try:
        click.echo("\n🔧 Available Conversion Backends")
        click.echo("=" * 50)
        
        click.echo("\n🔥 Firecracker MicroVMs")
        click.echo("  Description: Ultra-fast boot times (<150ms) with KVM isolation")
        click.echo("  Best for:")
        click.echo("    • Microservices")
        click.echo("    • Serverless functions")
        click.echo("    • High isolation requirements")
        click.echo("    • Fast startup times")
        click.echo("  Limitations:")
        click.echo("    • No GPU support")
        click.echo("    • No privileged operations")
        click.echo("    • Limited to 8GB RAM per VM")
        
        click.echo("\n📦 LXC Containers")
        click.echo("  Description: Full system containers with GPU support")
        click.echo("  Best for:")
        click.echo("    • GPU workloads")
        click.echo("    • Large applications")
        click.echo("    • System services")
        click.echo("    • Legacy applications")
        click.echo("  Limitations:")
        click.echo("    • Slower startup than Firecracker")
        click.echo("    • Shared kernel with host")
        
        click.echo("\n🎯 Auto Selection Criteria")
        click.echo("  Force LXC if:")
        click.echo("    • GPU/CUDA required")
        click.echo("    • Privileged access required")
        click.echo("    • SystemD services")
        click.echo("    • Large resource requirements (>8GB RAM)")
        click.echo("  Prefer Firecracker if:")
        click.echo("    • Fast startup required (<500ms)")
        click.echo("    • Microservice architecture")
        click.echo("    • Small resource footprint")
        
    except Exception as e:
        click.echo(f"❌ Failed to show backend information: {str(e)}", err=True)
        sys.exit(1)

def _get_user_context() -> Dict[str, Any]:
    """Get user context from saved token"""
    try:
        token_file = click.get_app_dir('vps-secure-compute') + '/token'
        if not os.path.exists(token_file):
            click.echo("❌ Not logged in. Please run 'vps-secure login' first.", err=True)
            sys.exit(1)
        
        with open(token_file, 'r') as f:
            token = f.read().strip()
        
        # Verify token (simplified - would use proper JWT verification)
        auth_manager = AuthenticationManager("your-jwt-secret-key")
        payload = auth_manager.verify_jwt_token(token)
        
        return {
            'user_id': payload['sub'],
            'email': payload['email'],
            'tenant_id': payload['tenant_id'],
            'role': payload['role']
        }
    
    except Exception as e:
        click.echo(f"❌ Authentication error: {str(e)}", err=True)
        click.echo("Please login again with 'vps-secure login'")
        sys.exit(1)

if __name__ == '__main__':
    main()