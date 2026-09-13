"""
Client-side resource quota tests
Tests quota enforcement from a user's perspective
"""

import pytest
import asyncio
from vps_secure_compute_manager.core.resource_manager import ResourceManager, ResourceRequest
from vps_secure_compute_manager.core.exceptions import ResourceQuotaExceeded
from vps_secure_compute_manager.iam.models import ResourceType

class TestClientResourceQuotas:
    """Test resource quota system from client perspective"""
    
    @pytest.mark.asyncio
    async def test_user_quota_enforcement(self, test_database, authenticated_user_context, resource_manager):
        """Test that user quotas are enforced"""
        with test_database["db_manager"].get_session() as session:
            # Create resource request within quota
            request = ResourceRequest(
                user_id=authenticated_user_context["user_id"],
                tenant_id=authenticated_user_context["tenant_id"],
                resource_type=ResourceType.FIRECRACKER_VM.value,
                amount=1,
                container_name="test-vm"
            )
            
            # Should succeed within quota
            available = resource_manager.check_resource_availability(session, request)
            assert available
            
            # Allocate the resource
            result = resource_manager.allocate_resources(session, request)
            assert result["success"]
            assert result["allocated_amount"] == 1
    
    @pytest.mark.asyncio
    async def test_quota_exceeded_rejection(self, test_database, authenticated_user_context, resource_manager):
        """Test that requests exceeding quotas are rejected"""
        with test_database["db_manager"].get_session() as session:
            # Get user's current quota for Firecracker VMs
            quota_info = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            
            firecracker_quota = None
            for quota in quota_info:
                if quota.resource_type == ResourceType.FIRECRACKER_VM.value:
                    firecracker_quota = quota
                    break
            
            if firecracker_quota:
                # Try to allocate more than available
                excessive_request = ResourceRequest(
                    user_id=authenticated_user_context["user_id"],
                    tenant_id=authenticated_user_context["tenant_id"],
                    resource_type=ResourceType.FIRECRACKER_VM.value,
                    amount=firecracker_quota.max_value + 1,  # Exceed quota
                    container_name="excessive-vm"
                )
                
                # Should be rejected
                available = resource_manager.check_resource_availability(session, excessive_request)
                assert not available
                
                with pytest.raises(ResourceQuotaExceeded):
                    resource_manager.allocate_resources(session, excessive_request)
    
    @pytest.mark.asyncio
    async def test_quota_tracking_accuracy(self, test_database, authenticated_user_context, resource_manager):
        """Test that quota usage is tracked accurately"""
        with test_database["db_manager"].get_session() as session:
            # Get initial quota state
            initial_quota_info = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            
            memory_quota = None
            for quota in initial_quota_info:
                if quota.resource_type == ResourceType.MEMORY_GB.value:
                    memory_quota = quota
                    break
            
            if memory_quota:
                initial_usage = memory_quota.current_value
                allocation_amount = 2.0  # 2GB
                
                # Allocate memory
                request = ResourceRequest(
                    user_id=authenticated_user_context["user_id"],
                    tenant_id=authenticated_user_context["tenant_id"],
                    resource_type=ResourceType.MEMORY_GB.value,
                    amount=allocation_amount,
                    container_name="memory-test"
                )
                
                resource_manager.allocate_resources(session, request)
                
                # Check updated quota
                updated_quota_info = resource_manager.get_user_quota_info(
                    session, authenticated_user_context["user_id"]
                )
                
                updated_memory_quota = None
                for quota in updated_quota_info:
                    if quota.resource_type == ResourceType.MEMORY_GB.value:
                        updated_memory_quota = quota
                        break
                
                # Verify usage increased correctly
                assert updated_memory_quota.current_value == initial_usage + allocation_amount
                assert updated_memory_quota.available == updated_memory_quota.max_value - updated_memory_quota.current_value
    
    @pytest.mark.asyncio 
    async def test_quota_deallocation(self, test_database, authenticated_user_context, resource_manager):
        """Test that resources are properly deallocated"""
        with test_database["db_manager"].get_session() as session:
            allocation_amount = 1.0  # 1 CPU core
            
            # Get initial state
            initial_quota_info = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            
            cpu_quota = None
            for quota in initial_quota_info:
                if quota.resource_type == ResourceType.CPU_CORES.value:
                    cpu_quota = quota
                    break
            
            if cpu_quota:
                initial_usage = cpu_quota.current_value
                
                # Allocate CPU
                allocate_request = ResourceRequest(
                    user_id=authenticated_user_context["user_id"],
                    tenant_id=authenticated_user_context["tenant_id"],
                    resource_type=ResourceType.CPU_CORES.value,
                    amount=allocation_amount,
                    container_name="cpu-test"
                )
                
                resource_manager.allocate_resources(session, allocate_request)
                
                # Verify allocation
                after_alloc_quota_info = resource_manager.get_user_quota_info(
                    session, authenticated_user_context["user_id"]
                )
                
                after_alloc_cpu_quota = None
                for quota in after_alloc_quota_info:
                    if quota.resource_type == ResourceType.CPU_CORES.value:
                        after_alloc_cpu_quota = quota
                        break
                
                assert after_alloc_cpu_quota.current_value == initial_usage + allocation_amount
                
                # Deallocate CPU
                deallocate_request = ResourceRequest(
                    user_id=authenticated_user_context["user_id"],
                    tenant_id=authenticated_user_context["tenant_id"],
                    resource_type=ResourceType.CPU_CORES.value,
                    amount=allocation_amount,
                    container_name="cpu-test"
                )
                
                resource_manager.deallocate_resources(session, deallocate_request)
                
                # Verify deallocation
                after_dealloc_quota_info = resource_manager.get_user_quota_info(
                    session, authenticated_user_context["user_id"]
                )
                
                after_dealloc_cpu_quota = None
                for quota in after_dealloc_quota_info:
                    if quota.resource_type == ResourceType.CPU_CORES.value:
                        after_dealloc_cpu_quota = quota
                        break
                
                assert after_dealloc_cpu_quota.current_value == initial_usage

class TestClientTenantQuotas:
    """Test tenant-level quota enforcement"""
    
    @pytest.mark.asyncio
    async def test_tenant_quota_enforcement(self, test_database, authenticated_user_context, resource_manager):
        """Test that tenant quotas are enforced"""
        with test_database["db_manager"].get_session() as session:
            # Get tenant quota info
            tenant_quota_info = resource_manager.get_tenant_quota_info(
                session, authenticated_user_context["tenant_id"]
            )
            
            # Find storage quota
            storage_quota = None
            for quota in tenant_quota_info:
                if quota.resource_type == ResourceType.STORAGE_GB.value:
                    storage_quota = quota
                    break
            
            if storage_quota:
                # Try to allocate storage within tenant quota
                request = ResourceRequest(
                    user_id=authenticated_user_context["user_id"],
                    tenant_id=authenticated_user_context["tenant_id"],
                    resource_type=ResourceType.STORAGE_GB.value,
                    amount=min(10.0, storage_quota.available),  # Within available
                    container_name="storage-test"
                )
                
                # Should succeed
                available = resource_manager.check_resource_availability(session, request)
                assert available
                
                result = resource_manager.allocate_resources(session, request)
                assert result["success"]
    
    @pytest.mark.asyncio
    async def test_tenant_vs_user_quota_interaction(self, test_database, authenticated_user_context, resource_manager):
        """Test interaction between tenant and user quotas"""
        with test_database["db_manager"].get_session() as session:
            # Get both user and tenant quotas
            user_quota_info = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            tenant_quota_info = resource_manager.get_tenant_quota_info(
                session, authenticated_user_context["tenant_id"]
            )
            
            # Find LXC container quotas
            user_lxc_quota = None
            tenant_lxc_quota = None
            
            for quota in user_quota_info:
                if quota.resource_type == ResourceType.LXC_CONTAINER.value:
                    user_lxc_quota = quota
                    break
            
            for quota in tenant_quota_info:
                if quota.resource_type == ResourceType.LXC_CONTAINER.value:
                    tenant_lxc_quota = quota
                    break
            
            if user_lxc_quota and tenant_lxc_quota:
                # The effective limit should be the minimum of user and tenant quotas
                effective_limit = min(user_lxc_quota.available, tenant_lxc_quota.available)
                
                if effective_limit > 0:
                    # Allocate up to effective limit
                    request = ResourceRequest(
                        user_id=authenticated_user_context["user_id"],
                        tenant_id=authenticated_user_context["tenant_id"],
                        resource_type=ResourceType.LXC_CONTAINER.value,
                        amount=min(1, effective_limit),
                        container_name="lxc-interaction-test"
                    )
                    
                    # Should succeed
                    available = resource_manager.check_resource_availability(session, request)
                    assert available
                    
                    result = resource_manager.allocate_resources(session, request)
                    assert result["success"]

class TestClientQuotaReporting:
    """Test quota reporting and visibility from client perspective"""
    
    @pytest.mark.asyncio
    async def test_user_quota_visibility(self, test_database, authenticated_user_context, resource_manager):
        """Test that users can see their quota information"""
        with test_database["db_manager"].get_session() as session:
            quota_info = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            
            # Should have quota info for all resource types
            assert len(quota_info) > 0
            
            # Check quota structure
            for quota in quota_info:
                assert hasattr(quota, 'resource_type')
                assert hasattr(quota, 'max_value')
                assert hasattr(quota, 'current_value')
                assert hasattr(quota, 'available')
                assert hasattr(quota, 'utilization_percent')
                
                # Basic sanity checks
                assert quota.max_value >= 0
                assert quota.current_value >= 0
                assert quota.current_value <= quota.max_value
                assert quota.available == quota.max_value - quota.current_value
                assert 0 <= quota.utilization_percent <= 100
    
    @pytest.mark.asyncio
    async def test_quota_utilization_calculation(self, test_database, authenticated_user_context, resource_manager):
        """Test that quota utilization is calculated correctly"""
        with test_database["db_manager"].get_session() as session:
            # Allocate some resources first
            allocation_amount = 1.0
            request = ResourceRequest(
                user_id=authenticated_user_context["user_id"],
                tenant_id=authenticated_user_context["tenant_id"],
                resource_type=ResourceType.NETWORK_MBPS.value,
                amount=allocation_amount,
                container_name="utilization-test"
            )
            
            # Get initial quota
            initial_quota_info = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            
            network_quota = None
            for quota in initial_quota_info:
                if quota.resource_type == ResourceType.NETWORK_MBPS.value:
                    network_quota = quota
                    break
            
            if network_quota and network_quota.available >= allocation_amount:
                initial_utilization = network_quota.utilization_percent
                
                # Allocate resources
                resource_manager.allocate_resources(session, request)
                
                # Get updated quota
                updated_quota_info = resource_manager.get_user_quota_info(
                    session, authenticated_user_context["user_id"]
                )
                
                updated_network_quota = None
                for quota in updated_quota_info:
                    if quota.resource_type == ResourceType.NETWORK_MBPS.value:
                        updated_network_quota = quota
                        break
                
                # Verify utilization increased
                assert updated_network_quota.utilization_percent > initial_utilization
                
                # Verify utilization calculation
                expected_utilization = (updated_network_quota.current_value / updated_network_quota.max_value) * 100
                assert abs(updated_network_quota.utilization_percent - expected_utilization) < 0.01
    
    @pytest.mark.asyncio
    async def test_resource_cost_calculation(self, resource_manager):
        """Test resource cost calculation from client perspective"""
        # Test different resource types
        test_cases = [
            (ResourceType.FIRECRACKER_VM.value, 1.0, 1.0),
            (ResourceType.LXC_CONTAINER.value, 1.0, 1.0),
            (ResourceType.MEMORY_GB.value, 8.0, 1.0),
            (ResourceType.CPU_CORES.value, 4.0, 1.0),
            (ResourceType.GPU_HOURS.value, 1.0, 8.0),  # 8 hours
            (ResourceType.STORAGE_GB.value, 100.0, 1.0),
            (ResourceType.NETWORK_MBPS.value, 1000.0, 1.0)
        ]
        
        for resource_type, amount, duration in test_cases:
            cost = resource_manager.calculate_resource_cost(resource_type, amount, duration)
            
            # Cost should be positive
            assert cost > 0
            
            # GPU hours should be more expensive due to duration
            if resource_type == ResourceType.GPU_HOURS.value and duration > 1:
                cost_1_hour = resource_manager.calculate_resource_cost(resource_type, amount, 1.0)
                assert cost > cost_1_hour

class TestClientQuotaManagement:
    """Test quota management scenarios from client perspective"""
    
    @pytest.mark.asyncio
    async def test_quota_insufficient_scenario(self, test_database, authenticated_user_context, resource_manager):
        """Test client behavior when quotas are insufficient"""
        with test_database["db_manager"].get_session() as session:
            # Get current GPU quota
            quota_info = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            
            gpu_quota = None
            for quota in quota_info:
                if quota.resource_type == ResourceType.GPU_HOURS.value:
                    gpu_quota = quota
                    break
            
            if gpu_quota:
                # Try to allocate more GPU hours than available
                excessive_request = ResourceRequest(
                    user_id=authenticated_user_context["user_id"],
                    tenant_id=authenticated_user_context["tenant_id"],
                    resource_type=ResourceType.GPU_HOURS.value,
                    amount=gpu_quota.max_value + 10,  # Exceed quota
                    container_name="gpu-excessive"
                )
                
                # Check availability (should be false)
                available = resource_manager.check_resource_availability(session, excessive_request)
                assert not available
                
                # Allocation should fail with proper error
                with pytest.raises(ResourceQuotaExceeded) as exc_info:
                    resource_manager.allocate_resources(session, excessive_request)
                
                # Verify error details
                assert exc_info.value.details["quota_type"] == ResourceType.GPU_HOURS.value
    
    @pytest.mark.asyncio
    async def test_multiple_resource_allocation(self, test_database, authenticated_user_context, resource_manager):
        """Test allocating multiple types of resources"""
        with test_database["db_manager"].get_session() as session:
            # Allocate multiple resource types for a container
            resource_requests = [
                ResourceRequest(
                    user_id=authenticated_user_context["user_id"],
                    tenant_id=authenticated_user_context["tenant_id"],
                    resource_type=ResourceType.MEMORY_GB.value,
                    amount=2.0,
                    container_name="multi-resource-test"
                ),
                ResourceRequest(
                    user_id=authenticated_user_context["user_id"],
                    tenant_id=authenticated_user_context["tenant_id"],
                    resource_type=ResourceType.CPU_CORES.value,
                    amount=1.0,
                    container_name="multi-resource-test"
                ),
                ResourceRequest(
                    user_id=authenticated_user_context["user_id"],
                    tenant_id=authenticated_user_context["tenant_id"],
                    resource_type=ResourceType.STORAGE_GB.value,
                    amount=10.0,
                    container_name="multi-resource-test"
                )
            ]
            
            # Check all resources are available
            all_available = True
            for request in resource_requests:
                if not resource_manager.check_resource_availability(session, request):
                    all_available = False
                    break
            
            if all_available:
                # Allocate all resources
                allocation_results = []
                for request in resource_requests:
                    result = resource_manager.allocate_resources(session, request)
                    allocation_results.append(result)
                
                # Verify all allocations succeeded
                for result in allocation_results:
                    assert result["success"]
                
                # Deallocate all resources
                for request in resource_requests:
                    dealloc_result = resource_manager.deallocate_resources(session, request)
                    assert dealloc_result["success"]
    
    @pytest.mark.asyncio
    async def test_quota_edge_cases(self, test_database, authenticated_user_context, resource_manager):
        """Test edge cases in quota management"""
        with test_database["db_manager"].get_session() as session:
            # Test zero allocation
            zero_request = ResourceRequest(
                user_id=authenticated_user_context["user_id"],
                tenant_id=authenticated_user_context["tenant_id"],
                resource_type=ResourceType.MEMORY_GB.value,
                amount=0.0,
                container_name="zero-test"
            )
            
            # Zero allocation should be allowed
            available = resource_manager.check_resource_availability(session, zero_request)
            assert available
            
            result = resource_manager.allocate_resources(session, zero_request)
            assert result["success"]
            assert result["allocated_amount"] == 0.0
            
            # Test very small allocation
            tiny_request = ResourceRequest(
                user_id=authenticated_user_context["user_id"],
                tenant_id=authenticated_user_context["tenant_id"],
                resource_type=ResourceType.STORAGE_GB.value,
                amount=0.001,  # 1MB
                container_name="tiny-test"
            )
            
            available = resource_manager.check_resource_availability(session, tiny_request)
            assert available
            
            result = resource_manager.allocate_resources(session, tiny_request)
            assert result["success"]
            assert result["allocated_amount"] == 0.001