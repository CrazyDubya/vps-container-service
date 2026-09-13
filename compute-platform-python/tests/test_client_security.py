"""
Client-side security tests
Tests security features from a user's perspective
"""

import pytest
import asyncio
import json
from vps_secure_compute_manager.core.security_manager import SecurityManager, SecurityEvent, ThreatLevel
from vps_secure_compute_manager.core.exceptions import SecurityViolation, TenantIsolationError
from vps_secure_compute_manager.iam.models import RoleType

class TestClientSecurityPolicies:
    """Test security policy enforcement from client perspective"""
    
    @pytest.mark.asyncio
    async def test_container_security_hardening(self, security_manager, authenticated_user_context):
        """Test that security hardening is applied to containers"""
        # Test Firecracker security policy
        firecracker_config = {
            "machine_config": {"vcpu_count": 2, "mem_size_mib": 512},
            "readonly_rootfs": False  # Should be overridden
        }
        
        secured_config = security_manager.validate_container_config(
            "firecracker", 
            firecracker_config, 
            authenticated_user_context
        )
        
        # Verify security hardening was applied
        assert secured_config["readonly_rootfs"] == True  # Should be enforced
        assert "rate_limiters" in secured_config  # Rate limiting should be added
        
        # Test LXC security policy
        lxc_config = {
            "lxc.unprivileged": "0"  # Should be overridden to "1"
        }
        
        secured_lxc_config = security_manager.validate_container_config(
            "lxc",
            lxc_config,
            authenticated_user_context
        )
        
        # Verify LXC hardening
        assert secured_lxc_config["lxc.unprivileged"] == "1"  # Should be enforced
        assert "lxc.cap.drop" in secured_lxc_config  # Capabilities should be dropped
    
    @pytest.mark.asyncio
    async def test_security_policy_enforcement(self, security_manager, authenticated_user_context):
        """Test that insecure configurations are rejected"""
        # Test dangerous Firecracker config
        dangerous_config = {
            "boot_args": "init=/bin/bash",  # Potentially dangerous
            "machine_config": {"vcpu_count": 100}  # Excessive resources
        }
        
        # Should apply restrictions
        secured_config = security_manager.validate_container_config(
            "firecracker",
            dangerous_config,
            authenticated_user_context
        )
        
        # Verify dangerous settings were restricted
        assert secured_config["machine_config"]["vcpu_count"] <= 4  # Should be limited
        assert "readonly_rootfs" in secured_config  # Security should be enforced
    
    @pytest.mark.asyncio
    async def test_tenant_isolation_enforcement(self, security_manager, test_database, auth_manager, test_config):
        """Test that tenant isolation is strictly enforced"""
        # Create second tenant
        second_tenant = test_database["db_manager"].create_tenant_with_defaults(
            name="isolated-tenant-security",
            display_name="Isolated Tenant Security",
            admin_email="security@isolated.local",
            admin_password="TestPassword123!"
        )
        
        # Get contexts for both tenants
        with test_database["db_manager"].get_session() as session:
            tenant1_auth = auth_manager.authenticate_user(
                session, test_config["test_user_email"], test_config["test_user_password"]
            )
            tenant2_auth = auth_manager.authenticate_user(
                session, "security@isolated.local", "TestPassword123!"
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
        
        # Test cross-tenant access violation
        from vps_secure_compute_manager.iam.auth import AuthorizationManager
        auth_manager_obj = AuthorizationManager()
        
        # Tenant 1 tries to access Tenant 2's resources
        with pytest.raises(TenantIsolationError):
            auth_manager_obj.enforce_tenant_isolation(
                tenant1_context, 
                tenant2_auth["tenant_id"]
            )
        
        # Tenant 2 tries to access Tenant 1's resources
        with pytest.raises(TenantIsolationError):
            auth_manager_obj.enforce_tenant_isolation(
                tenant2_context,
                tenant1_auth["tenant_id"]
            )

class TestClientSecurityMonitoring:
    """Test security monitoring from client perspective"""
    
    @pytest.mark.asyncio
    async def test_security_event_handling(self, security_manager, test_database):
        """Test security event detection and response"""
        # Create a mock security event
        security_event = SecurityEvent(
            event_type="suspicious_syscall",
            threat_level=ThreatLevel.HIGH,
            container_id="test-container-123",
            user_id="test-user-456",
            tenant_id="test-tenant-789",
            description="Suspicious system call detected",
            details={"syscall": "ptrace", "frequency": "high"},
            mitigation_actions=[]
        )
        
        # Handle the security event
        with test_database["db_manager"].get_session() as session:
            actions_taken = security_manager.handle_security_event(security_event, session)
            
            # Verify appropriate actions were taken for HIGH threat
            assert len(actions_taken) > 0
            assert any("capabilities_restricted" in action for action in actions_taken)
            assert any("monitoring_increased" in action for action in actions_taken)
    
    @pytest.mark.asyncio
    async def test_critical_security_event_response(self, security_manager, test_database):
        """Test response to critical security events"""
        # Create a critical security event
        critical_event = SecurityEvent(
            event_type="container_escape_attempt",
            threat_level=ThreatLevel.CRITICAL,
            container_id="compromised-container-123",
            user_id="test-user-456",
            tenant_id="test-tenant-789",
            description="Container escape attempt detected",
            details={"method": "kernel_exploit", "success": False},
            mitigation_actions=[]
        )
        
        # Handle the critical event
        with test_database["db_manager"].get_session() as session:
            actions_taken = security_manager.handle_security_event(critical_event, session)
            
            # Verify immediate response for CRITICAL threat
            assert len(actions_taken) > 0
            assert any("emergency_shutdown" in action for action in actions_taken)
            assert any("administrators_alerted" in action for action in actions_taken)
            assert any("container_quarantined" in action for action in actions_taken)
    
    @pytest.mark.asyncio
    async def test_security_audit_logging(self, test_database, security_manager):
        """Test that security events are properly logged"""
        # Create and handle a security event
        security_event = SecurityEvent(
            event_type="unauthorized_access_attempt",
            threat_level=ThreatLevel.MEDIUM,
            container_id="audit-test-container",
            user_id="audit-test-user",
            tenant_id="audit-test-tenant",
            description="Unauthorized access attempt logged",
            details={"source_ip": "192.168.1.100", "target": "/etc/passwd"},
            mitigation_actions=[]
        )
        
        with test_database["db_manager"].get_session() as session:
            security_manager.handle_security_event(security_event, session)
            
            # Verify audit log was created
            from vps_secure_compute_manager.iam.models import AuditLog
            audit_logs = session.query(AuditLog).filter(
                AuditLog.action == "security_event",
                AuditLog.resource_id == "audit-test-container"
            ).all()
            
            assert len(audit_logs) > 0
            audit_log = audit_logs[-1]
            assert audit_log.tenant_id == "audit-test-tenant"
            assert audit_log.user_id == "audit-test-user"
            assert audit_log.severity == "warning"  # MEDIUM threat
            
            # Verify details are stored as JSON
            details = json.loads(audit_log.details)
            assert details["event_type"] == "unauthorized_access_attempt"
            assert details["threat_level"] == "medium"

class TestClientSecurityCompliance:
    """Test security compliance from client perspective"""
    
    @pytest.mark.asyncio
    async def test_security_compliance_audit(self, security_manager, test_database):
        """Test security compliance auditing"""
        # Run compliance audit for tenant
        compliance_report = security_manager.audit_security_compliance(
            test_database["tenant_id"]
        )
        
        # Verify audit report structure
        assert "tenant_id" in compliance_report
        assert "audit_timestamp" in compliance_report
        assert "compliance_score" in compliance_report
        assert "findings" in compliance_report
        assert "recommendations" in compliance_report
        
        # Verify compliance score is reasonable
        assert 0 <= compliance_report["compliance_score"] <= 100
        
        # Verify findings are present
        assert isinstance(compliance_report["findings"], list)
        assert isinstance(compliance_report["recommendations"], list)
    
    @pytest.mark.asyncio
    async def test_container_security_validation(self, security_manager, authenticated_user_context):
        """Test that container configurations are security-validated"""
        # Test with secure configuration
        secure_config = {
            "memory_mb": 512,
            "cpu_count": 1,
            "readonly_rootfs": True,
            "network_isolation": True
        }
        
        # Should pass validation
        validated_config = security_manager.validate_container_config(
            "firecracker",
            secure_config,
            authenticated_user_context
        )
        
        assert validated_config is not None
        assert validated_config["readonly_rootfs"] == True
        
        # Test with potentially insecure configuration
        insecure_config = {
            "memory_mb": 16384,  # Very high memory
            "cpu_count": 32,     # Very high CPU
            "privileged": True,  # Dangerous setting
            "host_network": True # Dangerous network setting
        }
        
        # Should be hardened or rejected
        try:
            validated_config = security_manager.validate_container_config(
                "lxc",
                insecure_config,
                authenticated_user_context
            )
            
            # If not rejected, should be hardened
            assert validated_config["lxc.unprivileged"] == "1"  # Should be unprivileged
            assert validated_config["memory_mb"] <= 2048  # Should be limited
            
        except SecurityViolation:
            # Rejection is also acceptable for insecure config
            pass

class TestClientRoleBasedSecurity:
    """Test role-based security from client perspective"""
    
    @pytest.mark.asyncio
    async def test_user_permission_enforcement(self, test_database, auth_manager, test_config):
        """Test that user permissions are properly enforced"""
        from vps_secure_compute_manager.iam.auth import AuthorizationManager
        
        # Get user context
        with test_database["db_manager"].get_session() as session:
            auth_result = auth_manager.authenticate_user(
                session, test_config["test_user_email"], test_config["test_user_password"]
            )
        
        user_context = {
            "user_id": auth_result["user_id"],
            "tenant_id": auth_result["tenant_id"],
            "role": auth_result["role"]
        }
        
        auth_manager_obj = AuthorizationManager()
        
        # Test user can access their own resources
        can_access_own = auth_manager_obj.check_permission(
            user_context, "read", "containers", 
            resource_tenant_id=auth_result["tenant_id"],
            resource_user_id=auth_result["user_id"]
        )
        assert can_access_own
        
        # Test user cannot access other user's resources (if not admin)
        if auth_result["role"] != RoleType.PLATFORM_ADMIN.value:
            can_access_other = auth_manager_obj.check_permission(
                user_context, "read", "containers",
                resource_tenant_id=auth_result["tenant_id"],
                resource_user_id="other-user-id"
            )
            assert not can_access_other
    
    @pytest.mark.asyncio
    async def test_readonly_user_restrictions(self, test_database, auth_manager):
        """Test that readonly users have proper restrictions"""
        from vps_secure_compute_manager.iam.auth import AuthorizationManager
        from vps_secure_compute_manager.iam.models import User, RoleType
        
        # Create readonly user
        with test_database["db_manager"].get_session() as session:
            readonly_user = User(
                email="readonly@test.local",
                tenant_id=test_database["tenant_id"],
                role=RoleType.READONLY.value,
                is_active=True,
                is_verified=True
            )
            readonly_user.set_password("ReadOnlyPassword123!")
            session.add(readonly_user)
            session.commit()
            
            # Authenticate readonly user
            readonly_auth = auth_manager.authenticate_user(
                session, "readonly@test.local", "ReadOnlyPassword123!"
            )
        
        readonly_context = {
            "user_id": readonly_auth["user_id"],
            "tenant_id": readonly_auth["tenant_id"],
            "role": readonly_auth["role"]
        }
        
        auth_manager_obj = AuthorizationManager()
        
        # Readonly user can read their own resources
        can_read = auth_manager_obj.check_permission(
            readonly_context, "read", "containers",
            resource_tenant_id=readonly_auth["tenant_id"],
            resource_user_id=readonly_auth["user_id"]
        )
        assert can_read
        
        # Readonly user cannot create resources
        can_create = auth_manager_obj.check_permission(
            readonly_context, "create", "containers",
            resource_tenant_id=readonly_auth["tenant_id"],
            resource_user_id=readonly_auth["user_id"]
        )
        assert not can_create
        
        # Readonly user cannot update resources
        can_update = auth_manager_obj.check_permission(
            readonly_context, "update", "containers",
            resource_tenant_id=readonly_auth["tenant_id"],
            resource_user_id=readonly_auth["user_id"]
        )
        assert not can_update
        
        # Readonly user cannot delete resources
        can_delete = auth_manager_obj.check_permission(
            readonly_context, "delete", "containers",
            resource_tenant_id=readonly_auth["tenant_id"],
            resource_user_id=readonly_auth["user_id"]
        )
        assert not can_delete

class TestClientSecurityValidation:
    """Test security validation from client perspective"""
    
    @pytest.mark.asyncio
    async def test_input_validation_security(self, security_manager, authenticated_user_context):
        """Test that malicious inputs are properly validated"""
        # Test with potentially malicious container names
        malicious_configs = [
            {
                "name": "../../../etc/passwd",  # Path traversal
                "template": "python-cpu"
            },
            {
                "name": "test; rm -rf /",  # Command injection
                "template": "ubuntu-22.04"
            },
            {
                "name": "test<script>alert('xss')</script>",  # XSS attempt
                "template": "alpine-minimal"
            }
        ]
        
        for malicious_config in malicious_configs:
            # Should either sanitize or reject malicious input
            try:
                validated_config = security_manager.validate_container_config(
                    "lxc",
                    malicious_config,
                    authenticated_user_context
                )
                # If accepted, should be sanitized
                assert "../" not in validated_config.get("name", "")
                assert ";" not in validated_config.get("name", "")
                assert "<script>" not in validated_config.get("name", "")
            except SecurityViolation:
                # Rejection is also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_resource_limit_security(self, security_manager, authenticated_user_context):
        """Test that resource limits prevent abuse"""
        # Test excessive resource requests
        excessive_configs = [
            {
                "memory_mb": 1000000,  # 1TB RAM
                "cpu_count": 1000,     # 1000 CPUs
                "storage_gb": 100000   # 100TB storage
            },
            {
                "memory_mb": -1,       # Negative memory
                "cpu_count": 0,        # Zero CPUs
                "storage_gb": -100     # Negative storage
            }
        ]
        
        for excessive_config in excessive_configs:
            # Should apply reasonable limits
            validated_config = security_manager.validate_container_config(
                "firecracker",
                excessive_config,
                authenticated_user_context
            )
            
            # Verify limits are applied
            if "memory_mb" in validated_config:
                assert 64 <= validated_config["memory_mb"] <= 8192  # Reasonable range
            if "cpu_count" in validated_config:
                assert 1 <= validated_config["cpu_count"] <= 16     # Reasonable range
    
    @pytest.mark.asyncio
    async def test_configuration_tampering_protection(self, security_manager, authenticated_user_context):
        """Test protection against configuration tampering"""
        # Test attempts to override security settings
        tampered_config = {
            "readonly_rootfs": False,           # Try to disable security
            "lxc.apparmor.profile": "none",     # Try to disable AppArmor
            "lxc.seccomp.profile": "",          # Try to disable seccomp
            "lxc.cap.drop": "",                 # Try to restore capabilities
            "privileged": True                  # Try to run privileged
        }
        
        validated_config = security_manager.validate_container_config(
            "lxc",
            tampered_config,
            authenticated_user_context
        )
        
        # Verify security settings cannot be overridden
        assert validated_config["readonly_rootfs"] == True  # Should be enforced
        assert validated_config["lxc.apparmor.profile"] == "generated"  # Should be enforced
        assert validated_config["lxc.unprivileged"] == "1"  # Should be unprivileged
        assert "lxc.cap.drop" in validated_config  # Capabilities should be dropped