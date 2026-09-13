"""
VPS Secure Compute Manager - Multi-Tenant Firecracker + LXC Platform
Security-first design with proper user controls and tenant isolation
"""

__version__ = "1.0.0"
__author__ = "VPS Secure Compute Community"
__email__ = "security@conflost.com"

from .iam.models import User, Tenant, Role, Permission
from .iam.auth import AuthenticationManager, AuthorizationManager
from .backends.firecracker import FirecrackerBackend
from .backends.lxc import LXCBackend
from .core.security_manager import SecurityManager
from .core.resource_manager import ResourceManager

__all__ = [
    "User", "Tenant", "Role", "Permission",
    "AuthenticationManager", "AuthorizationManager", 
    "FirecrackerBackend", "LXCBackend",
    "SecurityManager", "ResourceManager"
]