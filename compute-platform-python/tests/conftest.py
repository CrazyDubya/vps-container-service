"""
Pytest configuration and fixtures for VPS Secure Compute Manager tests
Sets up test environment, database, and client connections
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
import subprocess
import time
import os
import json

from vps_secure_compute_manager.core.database import DatabaseManager
from vps_secure_compute_manager.iam.auth import AuthenticationManager
from vps_secure_compute_manager.backends.firecracker import FirecrackerBackend
from vps_secure_compute_manager.backends.lxc import LXCBackend
from vps_secure_compute_manager.core.security_manager import SecurityManager
from vps_secure_compute_manager.core.resource_manager import ResourceManager

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session") 
def test_config():
    """Test configuration"""
    return {
        "database_url": "sqlite:///test_vps_secure.db",
        "jwt_secret": "test-jwt-secret-key-for-testing-only",
        "admin_email": "admin@test.local",
        "admin_password": "TestAdminPassword123!",
        "test_tenant_name": "test-tenant",
        "test_tenant_display": "Test Tenant",
        "test_user_email": "user@test.local", 
        "test_user_password": "TestUserPassword123!",
        "firecracker_binary": "/usr/bin/firecracker",
        "lxc_path": "/tmp/test-lxc",
        "runtime_path": "/tmp/test-vps-runtime"
    }

@pytest.fixture(scope="session")
def test_database(test_config):
    """Set up test database with sample data"""
    # Clean up any existing test database
    db_file = test_config["database_url"].replace("sqlite:///", "")
    if os.path.exists(db_file):
        os.remove(db_file)
    
    # Initialize database manager
    db_manager = DatabaseManager(test_config["database_url"])
    
    # Create tables
    db_manager.create_tables()
    
    # Initialize default data
    db_manager.initialize_default_data()
    
    # Create test tenant and users
    tenant_result = db_manager.create_tenant_with_defaults(
        name=test_config["test_tenant_name"],
        display_name=test_config["test_tenant_display"],
        admin_email=test_config["test_user_email"],
        admin_password=test_config["test_user_password"]
    )
    
    yield {
        "db_manager": db_manager,
        "tenant_id": tenant_result["tenant_id"],
        "admin_user_id": tenant_result["admin_user_id"]
    }
    
    # Cleanup
    if os.path.exists(db_file):
        os.remove(db_file)

@pytest.fixture
def auth_manager(test_config):
    """Authentication manager for tests"""
    return AuthenticationManager(test_config["jwt_secret"])

@pytest.fixture
def authenticated_user_context(test_database, auth_manager, test_config):
    """Get authenticated user context for tests"""
    with test_database["db_manager"].get_session() as session:
        auth_result = auth_manager.authenticate_user(
            session,
            test_config["test_user_email"],
            test_config["test_user_password"]
        )
        
        return {
            "user_id": auth_result["user_id"],
            "email": auth_result["email"],
            "tenant_id": auth_result["tenant_id"],
            "role": auth_result["role"],
            "jwt_token": auth_result["jwt_token"]
        }

@pytest.fixture
def firecracker_backend(test_config):
    """Firecracker backend for testing"""
    # Create test directories
    os.makedirs(test_config["runtime_path"], exist_ok=True)
    
    # Create mock directories for testing
    mock_kernel_path = "/tmp/test-firecracker-kernels"
    mock_rootfs_path = "/tmp/test-firecracker-rootfs"
    os.makedirs(mock_kernel_path, exist_ok=True)
    os.makedirs(mock_rootfs_path, exist_ok=True)
    
    # Create mock template files for testing
    mock_templates = ["python-cpu", "nodejs-cpu", "alpine", "ubuntu"]
    for template in mock_templates:
        template_file = f"{mock_rootfs_path}/{template}.ext4"
        with open(template_file, "w") as f:
            f.write(f"Mock {template} rootfs file for testing")
    
    # Create mock kernel file
    kernel_file = f"{mock_kernel_path}/vmlinux.bin"
    with open(kernel_file, "w") as f:
        f.write("Mock kernel file for testing")
    
    # Mock Firecracker binary if not available
    if not os.path.exists(test_config["firecracker_binary"]):
        # Create mock firecracker binary for testing
        mock_binary = "/tmp/mock-firecracker"
        with open(mock_binary, "w") as f:
            f.write("#!/bin/bash\necho 'Mock Firecracker for testing'\nsleep 1\n")
        os.chmod(mock_binary, 0o755)
        test_config["firecracker_binary"] = mock_binary
    
    backend = FirecrackerBackend(
        firecracker_binary=test_config["firecracker_binary"],
        kernel_path=mock_kernel_path,
        rootfs_path=mock_rootfs_path,
        runtime_path=test_config["runtime_path"]
    )
    
    yield backend
    
    # Cleanup
    if os.path.exists(test_config["runtime_path"]):
        shutil.rmtree(test_config["runtime_path"])
    if os.path.exists(mock_kernel_path):
        shutil.rmtree(mock_kernel_path)
    if os.path.exists(mock_rootfs_path):
        shutil.rmtree(mock_rootfs_path)

@pytest.fixture
def lxc_backend(test_config):
    """LXC backend for testing"""
    # Create test LXC directory
    os.makedirs(test_config["lxc_path"], exist_ok=True)
    
    backend = LXCBackend(lxc_path=test_config["lxc_path"])
    
    yield backend
    
    # Cleanup
    if os.path.exists(test_config["lxc_path"]):
        shutil.rmtree(test_config["lxc_path"])

@pytest.fixture
def security_manager():
    """Security manager for testing"""
    return SecurityManager()

@pytest.fixture
def resource_manager():
    """Resource manager for testing"""
    return ResourceManager()

@pytest.fixture
def client_simulator(test_config, test_database, auth_manager):
    """Simulates a real client using the system"""
    class ClientSimulator:
        def __init__(self):
            self.config = test_config
            self.db_manager = test_database["db_manager"]
            self.auth_manager = auth_manager
            self.current_user = None
            self.jwt_token = None
        
        async def login(self, email, password):
            """Simulate user login"""
            with self.db_manager.get_session() as session:
                auth_result = self.auth_manager.authenticate_user(
                    session, email, password
                )
                self.current_user = auth_result
                self.jwt_token = auth_result["jwt_token"]
                return auth_result
        
        async def logout(self):
            """Simulate user logout"""
            if self.jwt_token:
                with self.db_manager.get_session() as session:
                    self.auth_manager.logout(session, self.jwt_token)
            self.current_user = None
            self.jwt_token = None
        
        def is_authenticated(self):
            """Check if user is authenticated"""
            return self.current_user is not None and self.jwt_token is not None
        
        def get_user_context(self):
            """Get current user context"""
            if not self.is_authenticated():
                raise Exception("User not authenticated")
            return {
                "user_id": self.current_user["user_id"],
                "email": self.current_user["email"],
                "tenant_id": self.current_user["tenant_id"],
                "role": self.current_user["role"]
            }
    
    return ClientSimulator()

@pytest.fixture
def cli_tester():
    """Helper for testing CLI commands"""
    class CLITester:
        def __init__(self):
            self.last_result = None
        
        def run_command(self, cmd_args, input_data=None, timeout=30):
            """Run CLI command and capture output"""
            try:
                result = subprocess.run(
                    cmd_args,
                    input=input_data,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                
                self.last_result = {
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "success": result.returncode == 0
                }
                return self.last_result
            except subprocess.TimeoutExpired:
                self.last_result = {
                    "returncode": -1,
                    "stdout": "",
                    "stderr": "Command timeout",
                    "success": False
                }
                return self.last_result
        
        def assert_success(self):
            """Assert last command was successful"""
            assert self.last_result is not None, "No command was run"
            assert self.last_result["success"], f"Command failed: {self.last_result['stderr']}"
        
        def assert_failure(self):
            """Assert last command failed"""
            assert self.last_result is not None, "No command was run"
            assert not self.last_result["success"], "Command should have failed"
        
        def get_output(self):
            """Get last command output"""
            if self.last_result:
                return self.last_result["stdout"]
            return ""
        
        def get_error(self):
            """Get last command error"""
            if self.last_result:
                return self.last_result["stderr"] 
            return ""
    
    return CLITester()

# Helper functions for tests
def wait_for_condition(condition_func, timeout=30, interval=1):
    """Wait for a condition to become true"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if condition_func():
            return True
        time.sleep(interval)
    return False

def create_test_file(path, content="test content"):
    """Create a test file with content"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    return path

def cleanup_test_files(*paths):
    """Clean up test files and directories"""
    for path in paths:
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)