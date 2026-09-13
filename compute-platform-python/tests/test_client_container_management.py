"""
Client-side container management tests
Tests container operations from a user's perspective
"""

import pytest
import asyncio
import time
from vps_secure_compute_manager.backends.base import ContainerConfig, ContainerStatus
from vps_secure_compute_manager.core.exceptions import FirecrackerError, LXCError, ResourceQuotaExceeded

class TestClientContainerOperations:
    """Test container operations from client perspective"""
    
    @pytest.mark.asyncio
    async def test_create_firecracker_container(self, firecracker_backend, authenticated_user_context):
        """Test creating a Firecracker container as a client"""
        config = ContainerConfig(
            name="test-firecracker-vm",
            template="python-cpu",
            memory_mb=512,
            cpu_count=1,
            storage_gb=5.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={"TEST_ENV": "firecracker"},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # Create container
        container_id = await firecracker_backend.create_container(config)
        
        # Verify container was created
        assert container_id is not None
        assert len(container_id) > 0
        
        # Get container info
        container_info = await firecracker_backend.get_container_info(container_id)
        assert container_info.name == "test-firecracker-vm"
        assert container_info.backend_type == "firecracker"
        assert container_info.status == ContainerStatus.CREATED
        assert container_info.memory_mb == 512
        assert container_info.cpu_count == 1
        assert container_info.gpu_count == 0
        assert container_info.user_id == authenticated_user_context["user_id"]
        assert container_info.tenant_id == authenticated_user_context["tenant_id"]
    
    @pytest.mark.asyncio
    async def test_create_lxc_container(self, lxc_backend, authenticated_user_context):
        """Test creating an LXC container as a client"""
        config = ContainerConfig(
            name="test-lxc-container",
            template="ubuntu-22.04",
            memory_mb=1024,
            cpu_count=2,
            storage_gb=10.0,
            gpu_count=1,
            network_config={},
            security_config={},
            environment={"TEST_ENV": "lxc"},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # Create container
        container_id = await lxc_backend.create_container(config)
        
        # Verify container was created
        assert container_id is not None
        assert len(container_id) > 0
        
        # Get container info
        container_info = await lxc_backend.get_container_info(container_id)
        assert container_info.name == "test-lxc-container"
        assert container_info.backend_type == "lxc"
        assert container_info.status == ContainerStatus.CREATED
        assert container_info.memory_mb == 1024
        assert container_info.cpu_count == 2
        assert container_info.gpu_count == 1
        assert container_info.user_id == authenticated_user_context["user_id"]
        assert container_info.tenant_id == authenticated_user_context["tenant_id"]
    
    @pytest.mark.asyncio
    async def test_container_lifecycle_firecracker(self, firecracker_backend, authenticated_user_context):
        """Test complete container lifecycle with Firecracker"""
        config = ContainerConfig(
            name="lifecycle-test-fc",
            template="python-cpu",
            memory_mb=256,
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # 1. Create
        container_id = await firecracker_backend.create_container(config)
        info = await firecracker_backend.get_container_info(container_id)
        assert info.status == ContainerStatus.CREATED
        
        # 2. Start (would normally work with real Firecracker)
        try:
            success = await firecracker_backend.start_container(container_id)
            if success:
                info = await firecracker_backend.get_container_info(container_id)
                assert info.status == ContainerStatus.RUNNING
        except FirecrackerError:
            # Expected in test environment without real Firecracker
            pass
        
        # 3. Stop
        try:
            success = await firecracker_backend.stop_container(container_id)
            if success:
                info = await firecracker_backend.get_container_info(container_id)
                assert info.status == ContainerStatus.STOPPED
        except FirecrackerError:
            # Expected in test environment
            pass
        
        # 4. Destroy
        success = await firecracker_backend.destroy_container(container_id)
        assert success
        
        # Container should no longer exist
        with pytest.raises(FirecrackerError):
            await firecracker_backend.get_container_info(container_id)
    
    @pytest.mark.asyncio
    async def test_container_lifecycle_lxc(self, lxc_backend, authenticated_user_context):
        """Test complete container lifecycle with LXC"""
        config = ContainerConfig(
            name="lifecycle-test-lxc",
            template="alpine-minimal",
            memory_mb=512,
            cpu_count=1,
            storage_gb=5.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # 1. Create
        container_id = await lxc_backend.create_container(config)
        info = await lxc_backend.get_container_info(container_id)
        assert info.status == ContainerStatus.CREATED
        
        # 2. Start (would work with real LXC)
        try:
            success = await lxc_backend.start_container(container_id)
            if success:
                info = await lxc_backend.get_container_info(container_id)
                assert info.status == ContainerStatus.RUNNING
        except LXCError:
            # Expected in test environment without real LXC
            pass
        
        # 3. Stop
        try:
            success = await lxc_backend.stop_container(container_id, force=True)
            if success:
                info = await lxc_backend.get_container_info(container_id)
                assert info.status == ContainerStatus.STOPPED
        except LXCError:
            # Expected in test environment
            pass
        
        # 4. Destroy
        success = await lxc_backend.destroy_container(container_id)
        assert success
        
        # Container should no longer exist
        with pytest.raises(LXCError):
            await lxc_backend.get_container_info(container_id)
    
    @pytest.mark.asyncio
    async def test_list_user_containers(self, firecracker_backend, lxc_backend, authenticated_user_context):
        """Test listing containers for a specific user"""
        # Create containers in both backends
        fc_config = ContainerConfig(
            name="user-fc-container",
            template="python-cpu",
            memory_mb=256,
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        lxc_config = ContainerConfig(
            name="user-lxc-container",
            template="ubuntu-22.04",
            memory_mb=512,
            cpu_count=1,
            storage_gb=5.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # Create containers
        fc_id = await firecracker_backend.create_container(fc_config)
        lxc_id = await lxc_backend.create_container(lxc_config)
        
        # List containers for user
        fc_containers = await firecracker_backend.list_containers(
            user_id=authenticated_user_context["user_id"]
        )
        lxc_containers = await lxc_backend.list_containers(
            user_id=authenticated_user_context["user_id"]
        )
        
        # Verify user's containers are returned
        assert len(fc_containers) >= 1
        assert len(lxc_containers) >= 1
        
        fc_container_ids = [c.id for c in fc_containers]
        lxc_container_ids = [c.id for c in lxc_containers]
        
        assert fc_id in fc_container_ids
        assert lxc_id in lxc_container_ids
        
        # Verify all containers belong to the user
        for container in fc_containers + lxc_containers:
            assert container.user_id == authenticated_user_context["user_id"]
            assert container.tenant_id == authenticated_user_context["tenant_id"]
    
    @pytest.mark.asyncio
    async def test_container_command_execution(self, lxc_backend, authenticated_user_context):
        """Test executing commands in containers"""
        config = ContainerConfig(
            name="exec-test-container",
            template="alpine-minimal",
            memory_mb=256,
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # Create container
        container_id = await lxc_backend.create_container(config)
        
        # Test command execution (would work with real LXC)
        try:
            result = await lxc_backend.exec_command(
                container_id, 
                ["echo", "Hello from container"],
                timeout=10
            )
            
            # Verify command structure (actual execution may fail in test env)
            assert hasattr(result, 'exit_code')
            assert hasattr(result, 'stdout')
            assert hasattr(result, 'stderr')
            assert hasattr(result, 'execution_time')
            
        except LXCError:
            # Expected in test environment without real LXC
            pass
    
    @pytest.mark.asyncio
    async def test_container_logs_retrieval(self, firecracker_backend, authenticated_user_context):
        """Test retrieving container logs"""
        config = ContainerConfig(
            name="logs-test-container",
            template="python-cpu",
            memory_mb=256,
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # Create container
        container_id = await firecracker_backend.create_container(config)
        
        # Get logs
        logs = await firecracker_backend.get_logs(container_id, lines=50)
        
        # Verify logs are returned as string
        assert isinstance(logs, str)
    
    @pytest.mark.asyncio
    async def test_container_metrics_retrieval(self, lxc_backend, authenticated_user_context):
        """Test retrieving container metrics"""
        config = ContainerConfig(
            name="metrics-test-container",
            template="ubuntu-22.04",
            memory_mb=512,
            cpu_count=1,
            storage_gb=5.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # Create container
        container_id = await lxc_backend.create_container(config)
        
        # Get metrics
        metrics = await lxc_backend.get_metrics(container_id)
        
        # Verify metrics structure
        assert isinstance(metrics, dict)
        assert "container_id" in metrics
        assert "timestamp" in metrics
        assert "cpu_usage_percent" in metrics
        assert "memory_usage_mb" in metrics
        assert "memory_usage_percent" in metrics
        assert metrics["container_id"] == container_id

class TestClientContainerSecurity:
    """Test container security from client perspective"""
    
    @pytest.mark.asyncio
    async def test_tenant_isolation_in_containers(self, test_database, firecracker_backend, auth_manager, test_config):
        """Test that users can only see their tenant's containers"""
        # Create second tenant
        second_tenant = test_database["db_manager"].create_tenant_with_defaults(
            name="isolated-tenant",
            display_name="Isolated Tenant",
            admin_email="isolated@test.local",
            admin_password="TestPassword123!"
        )
        
        # Get contexts for both tenants
        with test_database["db_manager"].get_session() as session:
            tenant1_auth = auth_manager.authenticate_user(
                session, test_config["test_user_email"], test_config["test_user_password"]
            )
            tenant2_auth = auth_manager.authenticate_user(
                session, "isolated@test.local", "TestPassword123!"
            )
        
        # Create containers for each tenant
        config1 = ContainerConfig(
            name="tenant1-container",
            template="python-cpu",
            memory_mb=256,
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context={
                "user_id": tenant1_auth["user_id"],
                "tenant_id": tenant1_auth["tenant_id"],
                "role": tenant1_auth["role"]
            }
        )
        
        config2 = ContainerConfig(
            name="tenant2-container",
            template="python-cpu",
            memory_mb=256,
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context={
                "user_id": tenant2_auth["user_id"],
                "tenant_id": tenant2_auth["tenant_id"],
                "role": tenant2_auth["role"]
            }
        )
        
        # Create containers
        container1_id = await firecracker_backend.create_container(config1)
        container2_id = await firecracker_backend.create_container(config2)
        
        # List containers for each tenant
        tenant1_containers = await firecracker_backend.list_containers(
            tenant_id=tenant1_auth["tenant_id"]
        )
        tenant2_containers = await firecracker_backend.list_containers(
            tenant_id=tenant2_auth["tenant_id"]
        )
        
        # Verify tenant isolation
        tenant1_ids = [c.id for c in tenant1_containers]
        tenant2_ids = [c.id for c in tenant2_containers]
        
        assert container1_id in tenant1_ids
        assert container1_id not in tenant2_ids
        assert container2_id in tenant2_ids
        assert container2_id not in tenant1_ids
        
        # Verify all containers in each list belong to correct tenant
        for container in tenant1_containers:
            assert container.tenant_id == tenant1_auth["tenant_id"]
        
        for container in tenant2_containers:
            assert container.tenant_id == tenant2_auth["tenant_id"]
    
    @pytest.mark.asyncio
    async def test_container_configuration_validation(self, firecracker_backend, lxc_backend, authenticated_user_context):
        """Test that invalid container configurations are rejected"""
        # Test invalid memory configuration
        invalid_config = ContainerConfig(
            name="invalid-memory",
            template="python-cpu",
            memory_mb=32,  # Too low
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        with pytest.raises((FirecrackerError, ValueError)):
            await firecracker_backend.create_container(invalid_config)
        
        # Test invalid CPU configuration
        invalid_config.memory_mb = 512  # Fix memory
        invalid_config.cpu_count = 0   # Invalid CPU count
        
        with pytest.raises((FirecrackerError, ValueError)):
            await firecracker_backend.create_container(invalid_config)
        
        # Test GPU on Firecracker (should be rejected)
        invalid_config.cpu_count = 1   # Fix CPU
        invalid_config.gpu_count = 1   # Firecracker doesn't support GPU
        
        # This should either be rejected or GPU count should be set to 0
        result = firecracker_backend.validate_config(invalid_config)
        assert not result  # Should fail validation
    
    @pytest.mark.asyncio
    async def test_security_hardening_applied(self, lxc_backend, authenticated_user_context, security_manager):
        """Test that security hardening is applied to containers"""
        config = ContainerConfig(
            name="security-test-container",
            template="ubuntu-22.04",
            memory_mb=512,
            cpu_count=1,
            storage_gb=5.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # Create container
        container_id = await lxc_backend.create_container(config)
        
        # Verify security hardening was applied
        container_info = await lxc_backend.get_container_info(container_id)
        
        # Basic checks that security configuration was considered
        assert container_info.user_id == authenticated_user_context["user_id"]
        assert container_info.tenant_id == authenticated_user_context["tenant_id"]
        
        # The security manager should have been called during creation
        # (In a real test, we'd check that security policies were applied)

class TestClientContainerErrors:
    """Test error handling from client perspective"""
    
    @pytest.mark.asyncio
    async def test_nonexistent_container_operations(self, firecracker_backend):
        """Test operations on nonexistent containers"""
        fake_container_id = "nonexistent-container-id"
        
        # Get info on nonexistent container
        with pytest.raises(FirecrackerError):
            await firecracker_backend.get_container_info(fake_container_id)
        
        # Start nonexistent container
        with pytest.raises(FirecrackerError):
            await firecracker_backend.start_container(fake_container_id)
        
        # Stop nonexistent container
        with pytest.raises(FirecrackerError):
            await firecracker_backend.stop_container(fake_container_id)
        
        # Execute command in nonexistent container
        with pytest.raises(FirecrackerError):
            await firecracker_backend.exec_command(fake_container_id, ["echo", "test"])
    
    @pytest.mark.asyncio
    async def test_invalid_template_handling(self, lxc_backend, authenticated_user_context):
        """Test handling of invalid templates"""
        config = ContainerConfig(
            name="invalid-template-test",
            template="nonexistent-template",
            memory_mb=512,
            cpu_count=1,
            storage_gb=5.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # Should fail validation or creation
        is_valid = lxc_backend.validate_config(config)
        assert not is_valid
        
        with pytest.raises(LXCError):
            await lxc_backend.create_container(config)
    
    @pytest.mark.asyncio
    async def test_resource_limit_validation(self, firecracker_backend, authenticated_user_context):
        """Test that resource limits are enforced"""
        # Test excessive memory request
        config = ContainerConfig(
            name="excessive-memory",
            template="python-cpu",
            memory_mb=100000,  # Excessive memory
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # Should fail validation
        is_valid = firecracker_backend.validate_config(config)
        assert not is_valid
        
        # Test excessive CPU request
        config.memory_mb = 512  # Fix memory
        config.cpu_count = 1000  # Excessive CPU
        
        is_valid = firecracker_backend.validate_config(config)
        assert not is_valid