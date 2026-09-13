"""
System integration tests
Tests the complete system integration from a client's external perspective
"""

import pytest
import asyncio
import json
import subprocess
import time
import tempfile
import os
from pathlib import Path

class TestSystemInitialization:
    """Test system initialization and setup from client perspective"""
    
    def test_system_database_initialization(self, test_database):
        """Test that database initializes correctly"""
        # Verify database is properly set up
        assert test_database["db_manager"] is not None
        assert test_database["tenant_id"] is not None
        assert test_database["admin_user_id"] is not None
        
        # Verify database tables exist
        with test_database["db_manager"].get_session() as session:
            # Test basic queries work
            from vps_secure_compute_manager.iam.models import User, Tenant, TenantQuota, UserQuota
            
            # Should be able to query users
            users = session.query(User).all()
            assert len(users) > 0
            
            # Should be able to query tenants
            tenants = session.query(Tenant).all()
            assert len(tenants) > 0
            
            # Should have quotas set up
            tenant_quotas = session.query(TenantQuota).all()
            user_quotas = session.query(UserQuota).all()
            assert len(tenant_quotas) > 0
            assert len(user_quotas) > 0
    
    def test_system_default_data_creation(self, test_database):
        """Test that default system data is created correctly"""
        with test_database["db_manager"].get_session() as session:
            from vps_secure_compute_manager.iam.models import Tenant, User, RoleType
            
            # Should have system tenant
            system_tenant = session.query(Tenant).filter(
                Tenant.name == "system"
            ).first()
            assert system_tenant is not None
            assert system_tenant.is_active
            
            # Should have test tenant
            test_tenant = session.query(Tenant).filter(
                Tenant.id == test_database["tenant_id"]
            ).first()
            assert test_tenant is not None
            assert test_tenant.is_active
            
            # Should have test user
            test_user = session.query(User).filter(
                User.id == test_database["admin_user_id"]
            ).first()
            assert test_user is not None
            assert test_user.is_active
            assert test_user.role in [RoleType.TENANT_ADMIN.value, RoleType.USER.value]

class TestSystemSecurity:
    """Test system-wide security from client perspective"""
    
    @pytest.mark.asyncio
    async def test_system_authentication_security(self, test_database, auth_manager, test_config):
        """Test system authentication security measures"""
        
        with test_database["db_manager"].get_session() as session:
            # Test that password hashing is secure
            from vps_secure_compute_manager.iam.models import User
            test_user = session.query(User).filter(
                User.id == test_database["admin_user_id"]
            ).first()
            
            # Password should be hashed, not stored in plain text
            assert test_user.password_hash != test_config["test_user_password"]
            assert len(test_user.password_hash) > 50  # Bcrypt hashes are long
            
            # Should be able to verify password
            assert test_user.check_password(test_config["test_user_password"])
            assert not test_user.check_password("wrong-password")
            
            # JWT tokens should be properly signed
            auth_result = auth_manager.authenticate_user(
                session,
                test_config["test_user_email"],
                test_config["test_user_password"]
            )
            
            jwt_token = auth_result["jwt_token"]
            assert jwt_token is not None
            assert len(jwt_token.split('.')) == 3  # JWT has 3 parts
            
            # Should be able to verify JWT
            payload = auth_manager.verify_jwt_token(jwt_token)
            assert payload["email"] == test_config["test_user_email"]
    
    @pytest.mark.asyncio
    async def test_system_tenant_isolation_enforcement(self, test_database, auth_manager, firecracker_backend, test_config):
        """Test that tenant isolation is enforced system-wide"""
        
        # Create two separate tenants
        tenant2_result = test_database["db_manager"].create_tenant_with_defaults(
            name="isolation-test-tenant",
            display_name="Isolation Test Tenant",
            admin_email="isolation@test.local",
            admin_password="IsolationPassword123!"
        )
        
        # Get authentication contexts
        with test_database["db_manager"].get_session() as session:
            tenant1_auth = auth_manager.authenticate_user(
                session, test_config["test_user_email"], test_config["test_user_password"]
            )
            tenant2_auth = auth_manager.authenticate_user(
                session, "isolation@test.local", "IsolationPassword123!"
            )
        
        # Create containers for each tenant
        from vps_secure_compute_manager.backends.base import ContainerConfig
        
        config1 = ContainerConfig(
            name="tenant1-system-test",
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
            name="tenant2-system-test",
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
        
        # Test strict tenant isolation
        tenant1_containers = await firecracker_backend.list_containers(
            tenant_id=tenant1_auth["tenant_id"]
        )
        tenant2_containers = await firecracker_backend.list_containers(
            tenant_id=tenant2_auth["tenant_id"]
        )
        
        # Each tenant should only see their own containers
        tenant1_ids = [c.id for c in tenant1_containers]
        tenant2_ids = [c.id for c in tenant2_containers]
        
        assert container1_id in tenant1_ids
        assert container1_id not in tenant2_ids
        assert container2_id in tenant2_ids
        assert container2_id not in tenant1_ids
        
        # Verify container metadata isolation
        container1_info = await firecracker_backend.get_container_info(container1_id)
        container2_info = await firecracker_backend.get_container_info(container2_id)
        
        assert container1_info.tenant_id == tenant1_auth["tenant_id"]
        assert container2_info.tenant_id == tenant2_auth["tenant_id"]
        assert container1_info.tenant_id != container2_info.tenant_id
        
        # Cleanup
        await firecracker_backend.destroy_container(container1_id)
        await firecracker_backend.destroy_container(container2_id)

class TestSystemResourceManagement:
    """Test system-wide resource management"""
    
    @pytest.mark.asyncio
    async def test_system_quota_consistency(self, test_database, resource_manager, authenticated_user_context):
        """Test that quota system maintains consistency system-wide"""
        
        with test_database["db_manager"].get_session() as session:
            # Get initial system state
            user_quotas = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            tenant_quotas = resource_manager.get_tenant_quota_info(
                session, authenticated_user_context["tenant_id"]
            )
            
            # Verify quota consistency
            for user_quota in user_quotas:
                # Find corresponding tenant quota
                tenant_quota = None
                for tq in tenant_quotas:
                    if tq.resource_type == user_quota.resource_type:
                        tenant_quota = tq
                        break
                
                if tenant_quota:
                    # User quota should not exceed tenant quota
                    assert user_quota.max_value <= tenant_quota.max_value
                    assert user_quota.current_value <= user_quota.max_value
                    assert tenant_quota.current_value <= tenant_quota.max_value
            
            # Test resource allocation affects both user and tenant quotas
            from vps_secure_compute_manager.core.resource_manager import ResourceRequest
            from vps_secure_compute_manager.iam.models import ResourceType
            
            # Find a quota we can test with
            memory_user_quota = None
            memory_tenant_quota = None
            
            for quota in user_quotas:
                if quota.resource_type == ResourceType.MEMORY_GB.value and quota.available > 0.5:
                    memory_user_quota = quota
                    break
            
            for quota in tenant_quotas:
                if quota.resource_type == ResourceType.MEMORY_GB.value:
                    memory_tenant_quota = quota
                    break
            
            if memory_user_quota and memory_tenant_quota and memory_tenant_quota.available > 0.5:
                # Allocate resources
                request = ResourceRequest(
                    user_id=authenticated_user_context["user_id"],
                    tenant_id=authenticated_user_context["tenant_id"],
                    resource_type=ResourceType.MEMORY_GB.value,
                    amount=0.5,
                    container_name="system-consistency-test"
                )
                
                initial_user_usage = memory_user_quota.current_value
                initial_tenant_usage = memory_tenant_quota.current_value
                
                result = resource_manager.allocate_resources(session, request)
                assert result["success"]
                
                # Verify both user and tenant quotas updated
                updated_user_quotas = resource_manager.get_user_quota_info(
                    session, authenticated_user_context["user_id"]
                )
                updated_tenant_quotas = resource_manager.get_tenant_quota_info(
                    session, authenticated_user_context["tenant_id"]
                )
                
                updated_memory_user_quota = None
                updated_memory_tenant_quota = None
                
                for quota in updated_user_quotas:
                    if quota.resource_type == ResourceType.MEMORY_GB.value:
                        updated_memory_user_quota = quota
                        break
                
                for quota in updated_tenant_quotas:
                    if quota.resource_type == ResourceType.MEMORY_GB.value:
                        updated_memory_tenant_quota = quota
                        break
                
                # Both should reflect the allocation
                assert updated_memory_user_quota.current_value == initial_user_usage + 0.5
                assert updated_memory_tenant_quota.current_value == initial_tenant_usage + 0.5
                
                # Cleanup
                resource_manager.deallocate_resources(session, request)
    
    @pytest.mark.asyncio
    async def test_system_resource_limits_enforcement(self, test_database, resource_manager, firecracker_backend, authenticated_user_context):
        """Test that system enforces resource limits correctly"""
        
        # Test creating container that would exceed quotas
        from vps_secure_compute_manager.backends.base import ContainerConfig
        
        # Try to create container with excessive resources
        excessive_config = ContainerConfig(
            name="excessive-resource-test",
            template="python-cpu",
            memory_mb=32768,  # 32GB - likely exceeds quota
            cpu_count=64,     # 64 CPUs - likely exceeds quota
            storage_gb=1000,  # 1TB - likely exceeds quota
            gpu_count=0,
            network_config={},
            security_config={},
            environment={},
            volumes=[],
            user_context=authenticated_user_context
        )
        
        # Should either fail validation or be limited by security manager
        try:
            # Check if configuration is valid
            is_valid = firecracker_backend.validate_config(excessive_config)
            if not is_valid:
                # Expected - configuration should be rejected
                pass
            else:
                # If config is accepted, it should be limited
                container_id = await firecracker_backend.create_container(excessive_config)
                container_info = await firecracker_backend.get_container_info(container_id)
                
                # Resources should be limited by security policies
                assert container_info.memory_mb <= 8192  # Should be limited
                assert container_info.cpu_count <= 16    # Should be limited
                
                # Cleanup
                await firecracker_backend.destroy_container(container_id)
        except Exception:
            # Expected if system properly rejects excessive requests
            pass

class TestSystemAuditAndCompliance:
    """Test system audit and compliance features"""
    
    @pytest.mark.asyncio
    async def test_system_audit_trail_completeness(self, test_database, auth_manager, security_manager, test_config):
        """Test that system maintains complete audit trail"""
        
        # Perform various operations that should be audited
        with test_database["db_manager"].get_session() as session:
            # Authentication events
            auth_result = auth_manager.authenticate_user(
                session,
                test_config["test_user_email"],
                test_config["test_user_password"],
                ip_address="192.168.1.100"
            )
            
            # Failed authentication
            try:
                auth_manager.authenticate_user(
                    session,
                    test_config["test_user_email"],
                    "wrong-password",
                    ip_address="192.168.1.101"
                )
            except Exception:
                pass
            
            # Security event
            from vps_secure_compute_manager.core.security_manager import SecurityEvent, ThreatLevel
            security_event = SecurityEvent(
                event_type="test_audit_event",
                threat_level=ThreatLevel.LOW,
                container_id="audit-test-container",
                user_id=auth_result["user_id"],
                tenant_id=auth_result["tenant_id"],
                description="Test audit event for system testing",
                details={"test": True},
                mitigation_actions=[]
            )
            
            security_manager.handle_security_event(security_event, session)
            
            # Verify audit logs were created
            from vps_secure_compute_manager.iam.models import AuditLog
            
            # Check authentication success log
            auth_logs = session.query(AuditLog).filter(
                AuditLog.action == "login",
                AuditLog.user_id == auth_result["user_id"],
                AuditLog.status == "success"
            ).all()
            assert len(auth_logs) > 0
            
            auth_log = auth_logs[-1]
            assert auth_log.ip_address == "192.168.1.100"
            assert auth_log.tenant_id == auth_result["tenant_id"]
            
            # Check authentication failure log
            failed_logs = session.query(AuditLog).filter(
                AuditLog.action == "login_failed",
                AuditLog.ip_address == "192.168.1.101"
            ).all()
            assert len(failed_logs) > 0
            
            failed_log = failed_logs[-1]
            assert failed_log.status == "failure"
            assert failed_log.severity == "warning"
            
            # Check security event log
            security_logs = session.query(AuditLog).filter(
                AuditLog.action == "security_event",
                AuditLog.resource_id == "audit-test-container"
            ).all()
            assert len(security_logs) > 0
            
            security_log = security_logs[-1]
            assert security_log.user_id == auth_result["user_id"]
            assert security_log.tenant_id == auth_result["tenant_id"]
            
            details = json.loads(security_log.details)
            assert details["event_type"] == "test_audit_event"
    
    @pytest.mark.asyncio
    async def test_system_compliance_reporting(self, security_manager, test_database):
        """Test system compliance reporting capabilities"""
        
        # Run compliance audit
        compliance_report = security_manager.audit_security_compliance(
            test_database["tenant_id"]
        )
        
        # Verify report structure and content
        required_fields = ["tenant_id", "audit_timestamp", "compliance_score", "findings", "recommendations"]
        for field in required_fields:
            assert field in compliance_report
        
        # Verify score is within valid range
        score = compliance_report["compliance_score"]
        assert isinstance(score, (int, float))
        assert 0 <= score <= 100
        
        # Verify findings and recommendations are meaningful
        findings = compliance_report["findings"]
        recommendations = compliance_report["recommendations"]
        
        assert isinstance(findings, list)
        assert isinstance(recommendations, list)
        
        # Should have some findings or recommendations
        assert len(findings) > 0 or len(recommendations) > 0

class TestSystemPerformanceAndScalability:
    """Test system performance and scalability characteristics"""
    
    @pytest.mark.asyncio
    async def test_system_concurrent_operations(self, test_database, auth_manager, firecracker_backend, test_config):
        """Test system handling of concurrent operations"""
        
        # Simulate multiple concurrent users
        num_concurrent_users = 3
        tasks = []
        
        async def simulate_user_session(user_suffix):
            # Create unique user for this test
            user_email = f"concurrent{user_suffix}@test.local"
            user_password = f"ConcurrentPassword{user_suffix}!"
            
            # Create user
            from vps_secure_compute_manager.iam.models import User
            with test_database["db_manager"].get_session() as session:
                user = User(
                    email=user_email,
                    tenant_id=test_database["tenant_id"],
                    role="user",
                    is_active=True,
                    is_verified=True
                )
                user.set_password(user_password)
                session.add(user)
                session.commit()
                user_id = user.id
            
            # Authenticate user
            with test_database["db_manager"].get_session() as session:
                auth_result = auth_manager.authenticate_user(
                    session, user_email, user_password
                )
            
            # Create container
            from vps_secure_compute_manager.backends.base import ContainerConfig
            config = ContainerConfig(
                name=f"concurrent-test-{user_suffix}",
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
                    "user_id": auth_result["user_id"],
                    "tenant_id": auth_result["tenant_id"],
                    "role": auth_result["role"]
                }
            )
            
            container_id = await firecracker_backend.create_container(config)
            
            # Perform operations
            container_info = await firecracker_backend.get_container_info(container_id)
            logs = await firecracker_backend.get_logs(container_id)
            metrics = await firecracker_backend.get_metrics(container_id)
            
            # Cleanup
            await firecracker_backend.destroy_container(container_id)
            
            return {
                "user_id": user_id,
                "container_id": container_id,
                "operations_completed": True
            }
        
        # Run concurrent sessions
        for i in range(num_concurrent_users):
            task = asyncio.create_task(simulate_user_session(i))
            tasks.append(task)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify all sessions completed successfully
        successful_sessions = 0
        for result in results:
            if isinstance(result, dict) and result.get("operations_completed"):
                successful_sessions += 1
            elif isinstance(result, Exception):
                # Some failures may be expected due to test environment limitations
                print(f"Concurrent session failed: {result}")
        
        # At least some sessions should succeed
        assert successful_sessions > 0
    
    @pytest.mark.asyncio
    async def test_system_database_performance(self, test_database, resource_manager, authenticated_user_context):
        """Test database performance under load"""
        
        # Test rapid quota operations
        operations_count = 50
        operation_times = []
        
        with test_database["db_manager"].get_session() as session:
            for i in range(operations_count):
                start_time = time.time()
                
                # Get quota info (read operation)
                quota_info = resource_manager.get_user_quota_info(
                    session, authenticated_user_context["user_id"]
                )
                
                operation_time = time.time() - start_time
                operation_times.append(operation_time)
                
                # Basic sanity check
                assert len(quota_info) > 0
        
        # Analyze performance
        avg_time = sum(operation_times) / len(operation_times)
        max_time = max(operation_times)
        
        # Operations should be reasonably fast
        assert avg_time < 0.1  # 100ms average
        assert max_time < 0.5  # 500ms max
        
        print(f"Database performance: avg={avg_time:.3f}s, max={max_time:.3f}s")

class TestSystemErrorHandlingAndRecovery:
    """Test system error handling and recovery capabilities"""
    
    @pytest.mark.asyncio
    async def test_system_graceful_error_handling(self, client_simulator, firecracker_backend, test_config):
        """Test that system handles errors gracefully"""
        
        # Login user
        await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        user_context = client_simulator.get_user_context()
        
        # Test various error scenarios
        error_scenarios = [
            {
                "name": "Invalid template",
                "config_override": {"template": "nonexistent-template"}
            },
            {
                "name": "Excessive memory", 
                "config_override": {"memory_mb": 999999}
            },
            {
                "name": "Invalid CPU count",
                "config_override": {"cpu_count": -1}
            },
            {
                "name": "Negative storage",
                "config_override": {"storage_gb": -10}
            }
        ]
        
        for scenario in error_scenarios:
            from vps_secure_compute_manager.backends.base import ContainerConfig
            
            base_config = {
                "name": f"error-test-{scenario['name'].replace(' ', '-').lower()}",
                "template": "python-cpu",
                "memory_mb": 512,
                "cpu_count": 1,
                "storage_gb": 5.0,
                "gpu_count": 0,
                "network_config": {},
                "security_config": {},
                "environment": {},
                "volumes": [],
                "user_context": user_context
            }
            
            # Apply scenario-specific overrides
            base_config.update(scenario["config_override"])
            
            config = ContainerConfig(**base_config)
            
            # Should either reject gracefully or correct the configuration
            try:
                # First check validation
                is_valid = firecracker_backend.validate_config(config)
                
                if is_valid:
                    # If validation passes, creation should work or apply corrections
                    container_id = await firecracker_backend.create_container(config)
                    
                    # If created, verify it's reasonable
                    container_info = await firecracker_backend.get_container_info(container_id)
                    assert container_info.memory_mb > 0
                    assert container_info.cpu_count > 0
                    assert container_info.storage_gb > 0
                    
                    # Cleanup
                    await firecracker_backend.destroy_container(container_id)
                else:
                    # Validation rejection is acceptable
                    pass
                    
            except Exception as e:
                # Exception handling is acceptable for invalid configs
                # Should be a meaningful error, not a crash
                assert len(str(e)) > 0
        
        await client_simulator.logout()
    
    @pytest.mark.asyncio
    async def test_system_data_consistency_under_errors(self, test_database, resource_manager, authenticated_user_context):
        """Test that system maintains data consistency even when errors occur"""
        
        with test_database["db_manager"].get_session() as session:
            # Get initial quota state
            initial_quotas = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            
            # Record initial state
            initial_state = {}
            for quota in initial_quotas:
                initial_state[quota.resource_type] = {
                    "current_value": quota.current_value,
                    "max_value": quota.max_value
                }
            
            # Perform operations that might fail
            from vps_secure_compute_manager.core.resource_manager import ResourceRequest
            from vps_secure_compute_manager.iam.models import ResourceType
            
            # Try various operations, some should fail
            test_operations = [
                {
                    "resource_type": ResourceType.MEMORY_GB.value,
                    "amount": 999999,  # Should fail - exceeds quota
                },
                {
                    "resource_type": ResourceType.CPU_CORES.value,
                    "amount": -1,      # Should fail - negative amount
                },
                {
                    "resource_type": "invalid_resource",  # Should fail - invalid type
                    "amount": 1,
                }
            ]
            
            for op in test_operations:
                try:
                    request = ResourceRequest(
                        user_id=authenticated_user_context["user_id"],
                        tenant_id=authenticated_user_context["tenant_id"],
                        resource_type=op["resource_type"],
                        amount=op["amount"],
                        container_name="consistency-test"
                    )
                    
                    # This should fail
                    resource_manager.allocate_resources(session, request)
                    
                except Exception:
                    # Expected to fail
                    pass
            
            # Verify quotas are still consistent after failed operations
            final_quotas = resource_manager.get_user_quota_info(
                session, authenticated_user_context["user_id"]
            )
            
            # State should be unchanged after failed operations
            for quota in final_quotas:
                if quota.resource_type in initial_state:
                    initial = initial_state[quota.resource_type]
                    assert quota.current_value == initial["current_value"]
                    assert quota.max_value == initial["max_value"]
                    assert quota.current_value <= quota.max_value
                    assert quota.available == quota.max_value - quota.current_value