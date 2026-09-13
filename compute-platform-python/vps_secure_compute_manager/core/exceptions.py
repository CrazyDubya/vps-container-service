"""
Custom exceptions for VPS Secure Compute Manager
Security-focused error handling with audit logging
"""

class VPSSecureComputeError(Exception):
    """Base exception for VPS Secure Compute Manager"""
    def __init__(self, message: str, error_code: str = None, details: dict = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

class AuthenticationError(VPSSecureComputeError):
    """Authentication failed"""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, "AUTH_FAILED")

class AuthorizationError(VPSSecureComputeError):
    """Authorization/permission denied"""
    def __init__(self, message: str = "Access denied"):
        super().__init__(message, "ACCESS_DENIED")

class TenantIsolationError(VPSSecureComputeError):
    """Tenant isolation boundary violated"""
    def __init__(self, message: str = "Tenant isolation violation"):
        super().__init__(message, "TENANT_ISOLATION_VIOLATION")

class ResourceQuotaExceeded(VPSSecureComputeError):
    """Resource quota exceeded"""
    def __init__(self, message: str = "Resource quota exceeded", quota_type: str = None):
        super().__init__(message, "QUOTA_EXCEEDED", {"quota_type": quota_type})

class SecurityViolation(VPSSecureComputeError):
    """Security policy violation"""
    def __init__(self, message: str = "Security policy violation", violation_type: str = None):
        super().__init__(message, "SECURITY_VIOLATION", {"violation_type": violation_type})

class ContainerError(VPSSecureComputeError):
    """Container operation failed"""
    def __init__(self, message: str = "Container operation failed", operation: str = None):
        super().__init__(message, "CONTAINER_ERROR", {"operation": operation})

class FirecrackerError(ContainerError):
    """Firecracker-specific error"""
    def __init__(self, message: str = "Firecracker operation failed"):
        super().__init__(message, "FIRECRACKER_ERROR")

class LXCError(ContainerError):
    """LXC-specific error"""
    def __init__(self, message: str = "LXC operation failed"):
        super().__init__(message, "LXC_ERROR")

class TemplateError(VPSSecureComputeError):
    """Template-related error"""
    def __init__(self, message: str = "Template error", template_name: str = None):
        super().__init__(message, "TEMPLATE_ERROR", {"template_name": template_name})

class NetworkError(VPSSecureComputeError):
    """Network configuration error"""
    def __init__(self, message: str = "Network error"):
        super().__init__(message, "NETWORK_ERROR")

class StorageError(VPSSecureComputeError):
    """Storage-related error"""
    def __init__(self, message: str = "Storage error"):
        super().__init__(message, "STORAGE_ERROR")

class ConfigurationError(VPSSecureComputeError):
    """Configuration error"""
    def __init__(self, message: str = "Configuration error", config_key: str = None):
        super().__init__(message, "CONFIG_ERROR", {"config_key": config_key})

class DatabaseError(VPSSecureComputeError):
    """Database operation error"""
    def __init__(self, message: str = "Database operation failed", operation: str = None):
        super().__init__(message, "DATABASE_ERROR", {"operation": operation})

class ConversionError(VPSSecureComputeError):
    """Docker conversion error"""
    def __init__(self, message: str = "Docker conversion failed", conversion_type: str = None):
        super().__init__(message, "CONVERSION_ERROR", {"conversion_type": conversion_type})