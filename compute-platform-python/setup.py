#!/usr/bin/env python3
"""
VPS Secure Compute Manager - Multi-Tenant Firecracker + LXC Platform
Security-first design with proper user controls and tenant isolation
"""

from setuptools import setup, find_packages
import os

def read_readme():
    with open(os.path.join(os.path.dirname(__file__), 'README.md'), 'r', encoding='utf-8') as f:
        return f.read()

setup(
    name="vps-secure-compute-manager",
    version="1.0.0",
    author="VPS Secure Compute Community",
    author_email="security@conflost.com",
    description="Multi-tenant secure compute platform with Firecracker microVMs and hardened LXC",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/vps-secure-compute/vps-secure-compute-manager",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: System :: Systems Administration",
        "Topic :: System :: Virtualization",
        "Topic :: Security",
        "Environment :: Console",
    ],
    python_requires=">=3.9",
    install_requires=[
        "pyyaml>=6.0",
        "requests>=2.28.0",
        "click>=8.0.0",
        "psutil>=5.9.0",
        "cryptography>=38.0.0",
        "pyjwt>=2.6.0",
        "bcrypt>=4.0.0",
        "sqlalchemy>=1.4.0",
        "alembic>=1.8.0",
        "pydantic>=1.10.0",
        "fastapi>=0.85.0",
        "uvicorn>=0.18.0",
        "aiofiles>=0.8.0",
        "asyncio-mqtt>=0.11.0",
        "prometheus-client>=0.15.0",
    ],
    extras_require={
        "firecracker": [
            "aiohttp>=3.8.0",
            "websockets>=10.0",
        ],
        "lxc": [
            "python3-lxc>=0.1",
            "psutil>=5.9.0",
        ],
        "security": [
            "auditd-python>=3.0.0",
            "selinux>=0.2.1",
            "apparmor>=3.0.0",
        ],
        "monitoring": [
            "prometheus-client>=0.15.0",
            "grafana-api>=1.0.3",
        ],
        "web": [
            "fastapi>=0.85.0",
            "uvicorn>=0.18.0",
            "jinja2>=3.1.0",
            "python-multipart>=0.0.5",
            "gunicorn>=20.1.0",
        ],
        "dev": [
            "pytest>=7.2.0",
            "pytest-asyncio>=0.21.0", 
            "pytest-mock>=3.10.0",
            "pytest-cov>=4.0.0",
            "pytest-xdist>=3.0.0",
            "black>=22.0.0",
            "mypy>=0.991",
            "bandit>=1.7.5",
            "safety>=2.3.0",
            "flake8>=5.0.0",
            "isort>=5.10.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "vps-secure=vps_secure_compute_manager.cli.main:main",
            "vps-secure-admin=vps_secure_compute_manager.cli.admin:main",
            "vps-secure-user=vps_secure_compute_manager.cli.user:main",
        ],
    },
    include_package_data=True,
    package_data={
        "vps_secure_compute_manager": [
            "templates/firecracker/*.yaml",
            "templates/lxc/*.yaml", 
            "templates/security/*.json",
            "config/security/*.yaml",
            "config/firecracker/*.json",
            "config/lxc/*.conf",
            "kernels/*.bin",
            "rootfs/*.ext4",
            "sql/migrations/*.sql",
        ],
    },
    project_urls={
        "Bug Reports": "https://github.com/vps-secure-compute/vps-secure-compute-manager/issues",
        "Documentation": "https://vps-secure-compute.readthedocs.io/",
        "Source": "https://github.com/vps-secure-compute/vps-secure-compute-manager",
        "Security": "https://github.com/vps-secure-compute/vps-secure-compute-manager/security",
    },
)