"""
Client-side authentication tests
Tests the system from a client perspective - login, logout, token management
"""

import pytest
import asyncio
import time
from vps_secure_compute_manager.core.exceptions import AuthenticationError, TenantIsolationError

class TestClientAuthentication:
    """Test authentication from client perspective"""
    
    @pytest.mark.asyncio
    async def test_successful_user_login(self, client_simulator, test_config):
        """Test successful user login flow"""
        # Test login
        auth_result = await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        
        # Verify authentication result
        assert auth_result["email"] == test_config["test_user_email"]
        assert auth_result["tenant_id"] is not None
        assert auth_result["role"] in ["tenant_admin", "user", "readonly"]
        assert auth_result["jwt_token"] is not None
        assert client_simulator.is_authenticated()
        
        # Verify user context
        user_context = client_simulator.get_user_context()
        assert user_context["email"] == test_config["test_user_email"]
        assert user_context["tenant_id"] == auth_result["tenant_id"]
    
    @pytest.mark.asyncio
    async def test_failed_login_invalid_credentials(self, client_simulator):
        """Test login failure with invalid credentials"""
        with pytest.raises(AuthenticationError):
            await client_simulator.login("invalid@test.local", "wrongpassword")
        
        assert not client_simulator.is_authenticated()
    
    @pytest.mark.asyncio
    async def test_failed_login_nonexistent_user(self, client_simulator):
        """Test login failure with nonexistent user"""
        with pytest.raises(AuthenticationError):
            await client_simulator.login("nonexistent@test.local", "password123")
        
        assert not client_simulator.is_authenticated()
    
    @pytest.mark.asyncio
    async def test_logout_flow(self, client_simulator, test_config):
        """Test user logout flow"""
        # Login first
        await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        assert client_simulator.is_authenticated()
        
        # Logout
        await client_simulator.logout()
        assert not client_simulator.is_authenticated()
        
        # Verify cannot get user context after logout
        with pytest.raises(Exception):
            client_simulator.get_user_context()
    
    @pytest.mark.asyncio
    async def test_jwt_token_validation(self, client_simulator, test_config, auth_manager):
        """Test JWT token validation"""
        # Login and get token
        auth_result = await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        
        jwt_token = auth_result["jwt_token"]
        
        # Verify token can be decoded
        payload = auth_manager.verify_jwt_token(jwt_token)
        assert payload["email"] == test_config["test_user_email"]
        assert payload["tenant_id"] == auth_result["tenant_id"]
        assert payload["role"] == auth_result["role"]
    
    @pytest.mark.asyncio
    async def test_invalid_jwt_token(self, auth_manager):
        """Test invalid JWT token handling"""
        invalid_token = "invalid.jwt.token"
        
        with pytest.raises(AuthenticationError):
            auth_manager.verify_jwt_token(invalid_token)
    
    @pytest.mark.asyncio 
    async def test_expired_jwt_token(self, auth_manager):
        """Test expired JWT token handling"""
        # Create token with very short expiry (simulated)
        import jwt
        import time
        from datetime import datetime, timedelta, timezone
        
        # Create expired token
        payload = {
            "sub": "test-user-id",
            "email": "test@test.local",
            "tenant_id": "test-tenant-id",
            "role": "user",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1)  # Expired 1 hour ago
        }
        
        expired_token = jwt.encode(payload, "test-jwt-secret-key-for-testing-only", algorithm="HS256")
        
        with pytest.raises(AuthenticationError, match="Token has expired"):
            auth_manager.verify_jwt_token(expired_token)
    
    @pytest.mark.asyncio
    async def test_tenant_isolation_in_authentication(self, test_database, auth_manager, test_config):
        """Test that users can only authenticate within their tenant"""
        # Create second tenant and user
        second_tenant = test_database["db_manager"].create_tenant_with_defaults(
            name="second-tenant",
            display_name="Second Tenant", 
            admin_email="admin2@test.local",
            admin_password="TestPassword123!"
        )
        
        # Login as first tenant user
        with test_database["db_manager"].get_session() as session:
            auth_result1 = auth_manager.authenticate_user(
                session,
                test_config["test_user_email"],
                test_config["test_user_password"]
            )
        
        # Login as second tenant user
        with test_database["db_manager"].get_session() as session:
            auth_result2 = auth_manager.authenticate_user(
                session,
                "admin2@test.local",
                "TestPassword123!"
            )
        
        # Verify they have different tenant IDs
        assert auth_result1["tenant_id"] != auth_result2["tenant_id"]
        assert auth_result1["tenant_id"] == test_database["tenant_id"]
        assert auth_result2["tenant_id"] == second_tenant["tenant_id"]
    
    @pytest.mark.asyncio
    async def test_session_management(self, client_simulator, test_config):
        """Test session creation and management"""
        # Login creates session
        auth_result = await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        
        # Verify session token exists
        assert "session_token" in auth_result
        assert auth_result["session_token"] is not None
        
        # Verify session expiry information
        assert "expires_at" in auth_result
        assert auth_result["expires_at"] is not None
    
    @pytest.mark.asyncio
    async def test_multiple_concurrent_sessions(self, test_database, auth_manager, test_config):
        """Test multiple concurrent sessions for same user"""
        sessions = []
        
        # Create multiple sessions
        for i in range(3):
            with test_database["db_manager"].get_session() as session:
                auth_result = auth_manager.authenticate_user(
                    session,
                    test_config["test_user_email"],
                    test_config["test_user_password"],
                    ip_address=f"192.168.1.{i+1}",
                    user_agent=f"TestClient-{i+1}"
                )
                sessions.append(auth_result)
        
        # Verify all sessions have different tokens
        session_tokens = [s["session_token"] for s in sessions]
        assert len(set(session_tokens)) == 3  # All unique
        
        # Verify all sessions have same user but different session data
        user_ids = [s["user_id"] for s in sessions]
        assert len(set(user_ids)) == 1  # Same user
    
    @pytest.mark.asyncio
    async def test_password_security_requirements(self, test_database, test_config):
        """Test password security requirements"""
        from vps_secure_compute_manager.iam.models import User
        
        with test_database["db_manager"].get_session() as session:
            user = User(
                email="testuser@test.local",
                tenant_id=test_database["tenant_id"],
                role="user"
            )
            
            # Test weak password rejection
            with pytest.raises(ValueError, match="Password must be at least 12 characters"):
                user.set_password("weak")
            
            # Test strong password acceptance
            user.set_password("StrongPassword123!")
            assert user.password_hash is not None
            
            # Test password verification
            assert user.check_password("StrongPassword123!")
            assert not user.check_password("WrongPassword")

class TestClientAuthenticationFlow:
    """Test complete authentication flows from client perspective"""
    
    @pytest.mark.asyncio
    async def test_complete_user_journey(self, client_simulator, test_config):
        """Test complete user authentication journey"""
        # 1. Start unauthenticated
        assert not client_simulator.is_authenticated()
        
        # 2. Login
        auth_result = await client_simulator.login(
            test_config["test_user_email"], 
            test_config["test_user_password"]
        )
        assert client_simulator.is_authenticated()
        
        # 3. Use system (get user context)
        user_context = client_simulator.get_user_context()
        assert user_context["email"] == test_config["test_user_email"]
        
        # 4. Logout
        await client_simulator.logout()
        assert not client_simulator.is_authenticated()
        
        # 5. Cannot use system after logout
        with pytest.raises(Exception):
            client_simulator.get_user_context()
    
    @pytest.mark.asyncio
    async def test_login_rate_limiting_simulation(self, client_simulator):
        """Test rapid login attempts (simulating rate limiting behavior)"""
        failed_attempts = 0
        
        # Simulate multiple rapid failed login attempts
        for i in range(5):
            try:
                await client_simulator.login("invalid@test.local", "wrongpassword")
            except AuthenticationError:
                failed_attempts += 1
        
        # All attempts should fail
        assert failed_attempts == 5
        assert not client_simulator.is_authenticated()
    
    @pytest.mark.asyncio
    async def test_authentication_audit_trail(self, test_database, auth_manager, test_config):
        """Test that authentication events are properly audited"""
        # Successful login
        with test_database["db_manager"].get_session() as session:
            auth_result = auth_manager.authenticate_user(
                session,
                test_config["test_user_email"],
                test_config["test_user_password"],
                ip_address="192.168.1.100"
            )
            
            # Check audit log was created
            from vps_secure_compute_manager.iam.models import AuditLog
            audit_logs = session.query(AuditLog).filter(
                AuditLog.action == "login",
                AuditLog.user_id == auth_result["user_id"]
            ).all()
            
            assert len(audit_logs) > 0
            audit_log = audit_logs[-1]  # Get most recent
            assert audit_log.ip_address == "192.168.1.100"
            assert audit_log.status == "success"
        
        # Failed login attempt
        with test_database["db_manager"].get_session() as session:
            try:
                auth_manager.authenticate_user(
                    session,
                    test_config["test_user_email"],
                    "wrongpassword",
                    ip_address="192.168.1.101"
                )
            except AuthenticationError:
                pass
            
            # Check failed login was audited
            failed_logs = session.query(AuditLog).filter(
                AuditLog.action == "login_failed",
                AuditLog.ip_address == "192.168.1.101"
            ).all()
            
            assert len(failed_logs) > 0
            failed_log = failed_logs[-1]
            assert failed_log.status == "failure"
            assert failed_log.severity == "warning"