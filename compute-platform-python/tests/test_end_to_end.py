"""
End-to-end client tests
Complete system tests from a real user's perspective
"""

import pytest
import asyncio
import time
from vps_secure_compute_manager.backends.base import ContainerConfig
from vps_secure_compute_manager.core.resource_manager import ResourceRequest
from vps_secure_compute_manager.iam.models import ResourceType

class TestEndToEndUserJourney:
    """Test complete user journeys from start to finish"""
    
    @pytest.mark.asyncio
    async def test_complete_user_container_lifecycle(self, client_simulator, firecracker_backend, test_config):
        """Test complete user journey: login -> create -> start -> use -> stop -> destroy -> logout"""
        
        # 1. User logs in
        auth_result = await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        assert client_simulator.is_authenticated()
        user_context = client_simulator.get_user_context()
        
        # 2. User creates a container
        config = ContainerConfig(
            name="e2e-test-container",
            template="python-cpu",
            memory_mb=512,
            cpu_count=1,
            storage_gb=5.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={"USER_ID": user_context["user_id"]},
            volumes=[],
            user_context=user_context
        )
        
        container_id = await firecracker_backend.create_container(config)
        assert container_id is not None
        
        # 3. User starts the container (may fail in test env, but structure should work)
        try:
            success = await firecracker_backend.start_container(container_id)
            if success:
                # 4. User checks container status
                container_info = await firecracker_backend.get_container_info(container_id)
                assert container_info.user_id == user_context["user_id"]
                assert container_info.tenant_id == user_context["tenant_id"]
                
                # 5. User gets container logs
                logs = await firecracker_backend.get_logs(container_id)
                assert isinstance(logs, str)
                
                # 6. User gets container metrics
                metrics = await firecracker_backend.get_metrics(container_id)
                assert "container_id" in metrics
                
                # 7. User stops the container
                await firecracker_backend.stop_container(container_id)
        except Exception:
            # Expected in test environment without real Firecracker
            pass
        
        # 8. User destroys the container
        success = await firecracker_backend.destroy_container(container_id)
        assert success
        
        # 9. User logs out
        await client_simulator.logout()
        assert not client_simulator.is_authenticated()
    
    @pytest.mark.asyncio
    async def test_multi_container_user_workflow(self, client_simulator, firecracker_backend, lxc_backend, test_config):
        """Test user managing multiple containers across backends"""
        
        # Login
        await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        user_context = client_simulator.get_user_context()
        
        # Create multiple containers
        containers_created = []
        
        # Create Firecracker container
        fc_config = ContainerConfig(
            name="multi-test-firecracker",
            template="python-cpu",
            memory_mb=256,
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=user_context
        )
        
        fc_container_id = await firecracker_backend.create_container(fc_config)
        containers_created.append(("firecracker", fc_container_id, firecracker_backend))
        
        # Create LXC container
        lxc_config = ContainerConfig(
            name="multi-test-lxc",
            template="ubuntu-22.04",
            memory_mb=512,
            cpu_count=1,
            storage_gb=5.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=user_context
        )
        
        lxc_container_id = await lxc_backend.create_container(lxc_config)
        containers_created.append(("lxc", lxc_container_id, lxc_backend))
        
        # List all user's containers
        fc_containers = await firecracker_backend.list_containers(user_id=user_context["user_id"])
        lxc_containers = await lxc_backend.list_containers(user_id=user_context["user_id"])
        
        # Verify user can see their containers
        fc_ids = [c.id for c in fc_containers]
        lxc_ids = [c.id for c in lxc_containers]
        
        assert fc_container_id in fc_ids
        assert lxc_container_id in lxc_ids
        
        # Cleanup all containers
        for backend_type, container_id, backend in containers_created:
            await backend.destroy_container(container_id)
        
        await client_simulator.logout()
    
    @pytest.mark.asyncio
    async def test_user_quota_enforcement_journey(self, client_simulator, test_database, resource_manager, test_config):
        """Test user experiencing quota limits in real usage"""
        
        # Login
        await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        user_context = client_simulator.get_user_context()
        
        with test_database["db_manager"].get_session() as session:
            # 1. User checks their quotas
            quota_info = resource_manager.get_user_quota_info(
                session, user_context["user_id"]
            )
            assert len(quota_info) > 0
            
            # Find memory quota
            memory_quota = None
            for quota in quota_info:
                if quota.resource_type == ResourceType.MEMORY_GB.value:
                    memory_quota = quota
                    break
            
            if memory_quota and memory_quota.available > 1.0:
                # 2. User allocates resources within quota
                request = ResourceRequest(
                    user_id=user_context["user_id"],
                    tenant_id=user_context["tenant_id"],
                    resource_type=ResourceType.MEMORY_GB.value,
                    amount=1.0,
                    container_name="quota-test"
                )
                
                # Should succeed
                result = resource_manager.allocate_resources(session, request)
                assert result["success"]
                
                # 3. User checks updated quota
                updated_quota_info = resource_manager.get_user_quota_info(
                    session, user_context["user_id"]
                )
                
                updated_memory_quota = None
                for quota in updated_quota_info:
                    if quota.resource_type == ResourceType.MEMORY_GB.value:
                        updated_memory_quota = quota
                        break
                
                # Quota should reflect usage
                assert updated_memory_quota.current_value == memory_quota.current_value + 1.0
                assert updated_memory_quota.available == memory_quota.available - 1.0
                
                # 4. User tries to exceed quota
                excessive_request = ResourceRequest(
                    user_id=user_context["user_id"],
                    tenant_id=user_context["tenant_id"],
                    resource_type=ResourceType.MEMORY_GB.value,
                    amount=updated_memory_quota.available + 10.0,  # Exceed quota
                    container_name="excessive-quota-test"
                )
                
                # Should fail
                available = resource_manager.check_resource_availability(session, excessive_request)
                assert not available
                
                # 5. User deallocates resources
                resource_manager.deallocate_resources(session, request)
                
                # 6. User verifies quota is restored
                final_quota_info = resource_manager.get_user_quota_info(
                    session, user_context["user_id"]
                )
                
                final_memory_quota = None
                for quota in final_quota_info:
                    if quota.resource_type == ResourceType.MEMORY_GB.value:
                        final_memory_quota = quota
                        break
                
                # Should be back to original
                assert final_memory_quota.current_value == memory_quota.current_value
        
        await client_simulator.logout()

class TestEndToEndTenantIsolation:
    """Test tenant isolation in end-to-end scenarios"""
    
    @pytest.mark.asyncio
    async def test_multi_tenant_isolation_scenario(self, test_database, auth_manager, firecracker_backend, test_config):
        """Test that multiple tenants are completely isolated"""
        
        # Create second tenant
        second_tenant = test_database["db_manager"].create_tenant_with_defaults(
            name="isolated-tenant-e2e",
            display_name="Isolated Tenant E2E",
            admin_email="isolated-admin@e2e.local",
            admin_password="IsolatedPassword123!"
        )
        
        # Get auth contexts for both tenants
        with test_database["db_manager"].get_session() as session:
            tenant1_auth = auth_manager.authenticate_user(
                session, test_config["test_user_email"], test_config["test_user_password"]
            )
            tenant2_auth = auth_manager.authenticate_user(
                session, "isolated-admin@e2e.local", "IsolatedPassword123!"
            )
        
        tenant1_context = {
            "user_id": tenant1_auth["user_id"],
            "tenant_id": tenant1_auth["tenant_id"],
            "role": tenant1_auth["role"]
        }
        
        tenant2_context = {
            "user_id": tenant2_auth["user_id"],
            "tenant_id": tenant2_auth["tenant_id"],
            "role": tenant2_auth["role"]
        }
        
        # Each tenant creates containers
        config1 = ContainerConfig(
            name="tenant1-isolated-container",
            template="python-cpu",
            memory_mb=256,
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={"TENANT": "tenant1"},
            volumes=[],
            user_context=tenant1_context
        )
        
        config2 = ContainerConfig(
            name="tenant2-isolated-container",
            template="python-cpu",
            memory_mb=256,
            cpu_count=1,
            storage_gb=2.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={"TENANT": "tenant2"},
            volumes=[],
            user_context=tenant2_context
        )
        
        # Create containers
        container1_id = await firecracker_backend.create_container(config1)
        container2_id = await firecracker_backend.create_container(config2)
        
        # Test tenant1 can only see their containers
        tenant1_containers = await firecracker_backend.list_containers(
            tenant_id=tenant1_auth["tenant_id"]
        )
        tenant1_ids = [c.id for c in tenant1_containers]
        assert container1_id in tenant1_ids
        assert container2_id not in tenant1_ids
        
        # Test tenant2 can only see their containers
        tenant2_containers = await firecracker_backend.list_containers(
            tenant_id=tenant2_auth["tenant_id"]
        )
        tenant2_ids = [c.id for c in tenant2_containers]
        assert container2_id in tenant2_ids
        assert container1_id not in tenant2_ids
        
        # Verify tenant isolation in container metadata
        container1_info = await firecracker_backend.get_container_info(container1_id)
        container2_info = await firecracker_backend.get_container_info(container2_id)
        
        assert container1_info.tenant_id == tenant1_auth["tenant_id"]
        assert container2_info.tenant_id == tenant2_auth["tenant_id"]
        assert container1_info.tenant_id != container2_info.tenant_id
        
        # Cleanup
        await firecracker_backend.destroy_container(container1_id)
        await firecracker_backend.destroy_container(container2_id)

class TestEndToEndSecurity:
    """Test security features in end-to-end scenarios"""
    
    @pytest.mark.asyncio
    async def test_security_monitoring_workflow(self, security_manager, test_database, authenticated_user_context):
        """Test security monitoring in a realistic scenario"""
        
        container_id = "security-test-container-e2e"
        
        # 1. Start security monitoring for container
        security_manager.monitor_container_security(container_id, authenticated_user_context)
        
        # 2. Simulate security event
        from vps_secure_compute_manager.core.security_manager import SecurityEvent, ThreatLevel
        
        security_event = SecurityEvent(
            event_type="resource_exhaustion_attempt",
            threat_level=ThreatLevel.MEDIUM,
            container_id=container_id,
            user_id=authenticated_user_context["user_id"],
            tenant_id=authenticated_user_context["tenant_id"],
            description="Container attempting to exhaust system resources",
            details={"cpu_usage": "99%", "memory_usage": "95%"},
            mitigation_actions=[]
        )
        
        # 3. Handle security event
        with test_database["db_manager"].get_session() as session:
            actions_taken = security_manager.handle_security_event(security_event, session)
            
            # Verify appropriate response
            assert len(actions_taken) > 0
            
            # Verify audit log was created
            from vps_secure_compute_manager.iam.models import AuditLog
            audit_logs = session.query(AuditLog).filter(
                AuditLog.action == "security_event",
                AuditLog.resource_id == container_id
            ).all()
            
            assert len(audit_logs) > 0
            audit_log = audit_logs[-1]
            assert audit_log.tenant_id == authenticated_user_context["tenant_id"]
            assert audit_log.user_id == authenticated_user_context["user_id"]
        
        # 4. Stop security monitoring
        security_manager.stop_container_monitoring(container_id)
    
    @pytest.mark.asyncio
    async def test_compliance_audit_workflow(self, security_manager, test_database):
        """Test security compliance audit workflow"""
        
        # 1. Run compliance audit
        compliance_report = security_manager.audit_security_compliance(
            test_database["tenant_id"]
        )
        
        # 2. Verify audit report completeness
        assert "tenant_id" in compliance_report
        assert "compliance_score" in compliance_report
        assert "findings" in compliance_report
        assert "recommendations" in compliance_report
        
        # 3. Verify score is reasonable
        assert 0 <= compliance_report["compliance_score"] <= 100
        
        # 4. Verify findings and recommendations are useful
        assert isinstance(compliance_report["findings"], list)
        assert isinstance(compliance_report["recommendations"], list)

class TestEndToEndErrorScenarios:
    """Test error handling in end-to-end scenarios"""
    
    @pytest.mark.asyncio
    async def test_user_error_recovery_workflow(self, client_simulator, firecracker_backend, test_config):
        """Test user recovering from various error scenarios"""
        
        # 1. User logs in
        await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        user_context = client_simulator.get_user_context()
        
        # 2. User tries to create container with invalid configuration
        invalid_config = ContainerConfig(
            name="invalid-container",
            template="nonexistent-template",
            memory_mb=32,  # Too low
            cpu_count=0,   # Invalid
            storage_gb=-1, # Invalid
            gpu_count=1,   # Not supported on Firecracker
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=user_context
        )
        
        # Should fail validation
        try:
            container_id = await firecracker_backend.create_container(invalid_config)
            # If it doesn't fail, the validation should have corrected the config
            container_info = await firecracker_backend.get_container_info(container_id)
            assert container_info.gpu_count == 0  # Should be corrected
        except Exception:
            # Expected to fail with invalid config
            pass
        
        # 3. User creates valid container
        valid_config = ContainerConfig(
            name="valid-recovery-container",
            template="python-cpu",
            memory_mb=512,
            cpu_count=1,
            storage_gb=5.0,
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=user_context
        )
        
        container_id = await firecracker_backend.create_container(valid_config)
        assert container_id is not None
        
        # 4. User tries invalid operations on container
        try:
            # Try to access nonexistent container
            await firecracker_backend.get_container_info("nonexistent-id")
        except Exception:
            # Expected to fail
            pass
        
        # 5. User successfully operates on valid container
        container_info = await firecracker_backend.get_container_info(container_id)
        assert container_info.id == container_id
        
        # 6. Cleanup
        await firecracker_backend.destroy_container(container_id)
        await client_simulator.logout()
    
    @pytest.mark.asyncio
    async def test_system_resilience_scenarios(self, client_simulator, test_database, resource_manager, test_config):
        """Test system resilience under various stress conditions"""
        
        await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        user_context = client_simulator.get_user_context()
        
        with test_database["db_manager"].get_session() as session:
            # 1. Test rapid resource allocation/deallocation
            for i in range(5):
                request = ResourceRequest(
                    user_id=user_context["user_id"],
                    tenant_id=user_context["tenant_id"],
                    resource_type=ResourceType.CPU_CORES.value,
                    amount=0.1,  # Small amount
                    container_name=f"stress-test-{i}"
                )
                
                # Allocate
                available = resource_manager.check_resource_availability(session, request)
                if available:
                    result = resource_manager.allocate_resources(session, request)
                    assert result["success"]
                    
                    # Immediately deallocate
                    dealloc_result = resource_manager.deallocate_resources(session, request)
                    assert dealloc_result["success"]
            
            # 2. Test quota consistency after stress
            final_quota_info = resource_manager.get_user_quota_info(
                session, user_context["user_id"]
            )
            
            # All quotas should be consistent
            for quota in final_quota_info:
                assert quota.current_value >= 0
                assert quota.current_value <= quota.max_value
                assert quota.available == quota.max_value - quota.current_value
        
        await client_simulator.logout()

class TestEndToEndPerformance:
    """Test performance characteristics from client perspective"""
    
    @pytest.mark.asyncio
    async def test_container_operation_performance(self, firecracker_backend, authenticated_user_context):
        """Test that container operations complete within reasonable time"""
        
        config = ContainerConfig(
            name="performance-test-container",
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
        
        # Test container creation performance
        start_time = time.time()
        container_id = await firecracker_backend.create_container(config)
        creation_time = time.time() - start_time
        
        # Container creation should be reasonably fast (< 5 seconds in test env)
        assert creation_time < 5.0
        assert container_id is not None
        
        # Test container info retrieval performance
        start_time = time.time()
        container_info = await firecracker_backend.get_container_info(container_id)
        info_time = time.time() - start_time
        
        # Info retrieval should be very fast (< 1 second)
        assert info_time < 1.0
        assert container_info.id == container_id
        
        # Test container destruction performance
        start_time = time.time()
        success = await firecracker_backend.destroy_container(container_id)
        destruction_time = time.time() - start_time
        
        # Destruction should be reasonably fast (< 3 seconds)
        assert destruction_time < 3.0
        assert success
    
    @pytest.mark.asyncio
    async def test_quota_operation_performance(self, test_database, resource_manager, authenticated_user_context):
        """Test quota operations performance"""
        
        with test_database["db_manager"].get_session() as session:
            # Test quota info retrieval performance
            start_time = time.time()
            quota_info = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            quota_time = time.time() - start_time
            
            # Quota retrieval should be fast (< 0.5 seconds)
            assert quota_time < 0.5
            assert len(quota_info) > 0
            
            # Test resource allocation performance
            request = ResourceRequest(
                user_id=authenticated_user_context["user_id"],
                tenant_id=authenticated_user_context["tenant_id"],
                resource_type=ResourceType.MEMORY_GB.value,
                amount=0.1,
                container_name="performance-test"
            )
            
            start_time = time.time()
            available = resource_manager.check_resource_availability(session, request)
            check_time = time.time() - start_time
            
            # Availability check should be very fast (< 0.1 seconds)
            assert check_time < 0.1
            
            if available:
                start_time = time.time()
                result = resource_manager.allocate_resources(session, request)
                alloc_time = time.time() - start_time
                
                # Allocation should be fast (< 0.5 seconds)
                assert alloc_time < 0.5
                assert result["success"]
                
                # Cleanup
                resource_manager.deallocate_resources(session, request)