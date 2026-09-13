#!/usr/bin/env python3
"""
Client Test Runner for VPS Secure Compute Manager
Comprehensive testing from external client perspective
"""

import sys
import os
import subprocess
import time
import argparse
from pathlib import Path

def run_test_suite(test_type="all", verbose=False, coverage=False):
    """Run comprehensive client tests"""
    
    # Set up environment
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # Install test dependencies
    print("🔧 Installing test dependencies...")
    subprocess.run([
        sys.executable, "-m", "pip", "install", "-e", ".[dev,firecracker,lxc,security]"
    ], check=True)
    
    # Build test command
    cmd = [sys.executable, "-m", "pytest"]
    
    if verbose:
        cmd.extend(["-v", "-s"])
    
    if coverage:
        cmd.extend([
            "--cov=vps_secure_compute_manager",
            "--cov-report=html",
            "--cov-report=term-missing"
        ])
    
    # Select test types
    test_files = []
    
    if test_type in ["all", "auth"]:
        test_files.append("tests/test_client_authentication.py")
    
    if test_type in ["all", "containers"]:
        test_files.append("tests/test_client_container_management.py")
    
    if test_type in ["all", "quotas"]:
        test_files.append("tests/test_client_resource_quotas.py")
    
    if test_type in ["all", "security"]:
        test_files.append("tests/test_client_security.py")
    
    if test_type in ["all", "cli"]:
        test_files.append("tests/test_client_cli.py")
    
    if test_type in ["all", "e2e"]:
        test_files.append("tests/test_end_to_end.py")
    
    if test_type in ["all", "integration"]:
        test_files.append("tests/test_system_integration.py")
    
    cmd.extend(test_files)
    
    # Add additional pytest options
    cmd.extend([
        "--tb=short",
        "--durations=10",
        "-x",  # Stop on first failure for faster feedback
    ])
    
    print(f"🧪 Running client tests: {test_type}")
    print(f"📋 Command: {' '.join(cmd)}")
    
    # Run tests
    start_time = time.time()
    
    try:
        result = subprocess.run(cmd, check=False)
        
        duration = time.time() - start_time
        
        if result.returncode == 0:
            print(f"✅ All tests passed! ({duration:.2f}s)")
            return True
        else:
            print(f"❌ Tests failed! ({duration:.2f}s)")
            return False
            
    except KeyboardInterrupt:
        print("\n⚠️ Tests interrupted by user")
        return False
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        return False

def run_performance_tests():
    """Run performance-focused tests"""
    print("🚀 Running performance tests...")
    
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_end_to_end.py::TestEndToEndPerformance",
        "tests/test_system_integration.py::TestSystemPerformanceAndScalability",
        "-v", "--tb=short"
    ]
    
    result = subprocess.run(cmd, check=False)
    return result.returncode == 0

def run_security_tests():
    """Run security-focused tests"""
    print("🛡️ Running security tests...")
    
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_client_security.py",
        "tests/test_system_integration.py::TestSystemSecurity",
        "-v", "--tb=short"
    ]
    
    result = subprocess.run(cmd, check=False)
    return result.returncode == 0

def run_smoke_tests():
    """Run basic smoke tests"""
    print("💨 Running smoke tests...")
    
    # Select key tests that verify basic functionality
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_client_authentication.py::TestClientAuthentication::test_successful_user_login",
        "tests/test_client_container_management.py::TestClientContainerOperations::test_create_firecracker_container",
        "tests/test_client_resource_quotas.py::TestClientResourceQuotas::test_user_quota_enforcement",
        "tests/test_system_integration.py::TestSystemInitialization::test_system_database_initialization",
        "-v", "--tb=short"
    ]
    
    result = subprocess.run(cmd, check=False)
    return result.returncode == 0

def main():
    """Main test runner"""
    parser = argparse.ArgumentParser(description="VPS Secure Compute Manager Client Test Runner")
    
    parser.add_argument(
        "--type", 
        choices=["all", "auth", "containers", "quotas", "security", "cli", "e2e", "integration", "performance", "smoke"],
        default="all",
        help="Type of tests to run"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    parser.add_argument(
        "--coverage", "-c",
        action="store_true",
        help="Enable coverage reporting"
    )
    
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only smoke tests for quick validation"
    )
    
    args = parser.parse_args()
    
    print("🔐 VPS Secure Compute Manager - Client Test Suite")
    print("=" * 60)
    
    success = True
    
    if args.quick:
        success = run_smoke_tests()
    elif args.type == "performance":
        success = run_performance_tests()
    elif args.type == "security":
        success = run_security_tests()
    else:
        success = run_test_suite(args.type, args.verbose, args.coverage)
    
    print("\n" + "=" * 60)
    
    if success:
        print("🎉 All tests completed successfully!")
        print("✅ System is ready for client use")
        sys.exit(0)
    else:
        print("💥 Some tests failed!")
        print("❌ System may have issues - check logs above")
        sys.exit(1)

if __name__ == "__main__":
    main()