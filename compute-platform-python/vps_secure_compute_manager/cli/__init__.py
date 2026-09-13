"""
Command Line Interface for VPS Secure Compute Manager
"""

from .main import main
from .admin import admin_main  
from .user import user_main

__all__ = ["main", "admin_main", "user_main"]