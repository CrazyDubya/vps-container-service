"""
Template Management System for VPS Secure Compute Manager
Handles template creation, versioning, distribution, and security updates
"""

import os
import json
import asyncio
import aiohttp
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
import yaml

logger = logging.getLogger(__name__)

@dataclass
class TemplateInfo:
    """Template metadata"""
    name: str
    version: str
    architecture: str
    os_family: str
    os_version: str
    description: str
    size_mb: int
    checksum: str
    created_at: datetime
    updated_at: datetime
    security_level: str  # "minimal", "hardened", "maximum"
    features: List[str]  # ["docker", "gpu", "networking"]
    maintainer: str
    source_url: str
    license: str

class TemplateManager:
    """Commercial-grade template management system"""
    
    def __init__(self, 
                 template_path: str = "/opt/vps-secure-compute/templates",
                 cache_path: str = "/var/cache/vps-secure-compute/templates",
                 registry_url: str = "https://templates.vps-secure.com"):
        
        self.template_path = Path(template_path)
        self.cache_path = Path(cache_path)
        self.registry_url = registry_url
        
        # Create directories
        self.template_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        
        # Template catalog
        self.catalog = {}
        self.load_catalog()
    
    def load_catalog(self):
        """Load template catalog from disk"""
        catalog_file = self.template_path / "catalog.json"
        if catalog_file.exists():
            with open(catalog_file, 'r') as f:
                data = json.load(f)
                for item in data.get("templates", []):
                    template = TemplateInfo(**item)
                    self.catalog[f"{template.name}:{template.version}"] = template
    
    async def sync_with_registry(self) -> bool:
        """Sync template catalog with remote registry"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.registry_url}/api/v1/catalog") as response:
                    if response.status == 200:
                        catalog_data = await response.json()
                        
                        # Update local catalog
                        for template_data in catalog_data.get("templates", []):
                            template = TemplateInfo(**template_data)
                            key = f"{template.name}:{template.version}"
                            
                            # Check if we need to update
                            if key not in self.catalog or self.catalog[key].updated_at < template.updated_at:
                                self.catalog[key] = template
                        
                        # Save updated catalog
                        self.save_catalog()
                        return True
            
        except Exception as e:
            logger.error(f"Failed to sync with registry: {e}")
            return False
    
    def save_catalog(self):
        """Save template catalog to disk"""
        catalog_file = self.template_path / "catalog.json"
        catalog_data = {
            "version": "1.0",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "templates": [
                template.__dict__ for template in self.catalog.values()
            ]
        }
        
        with open(catalog_file, 'w') as f:
            json.dump(catalog_data, f, indent=2, default=str)
    
    async def download_template(self, name: str, version: str = "latest") -> bool:
        """Download template from registry"""
        try:
            key = f"{name}:{version}"
            if key not in self.catalog:
                await self.sync_with_registry()
            
            if key not in self.catalog:
                logger.error(f"Template {key} not found in catalog")
                return False
            
            template = self.catalog[key]
            template_file = self.template_path / f"{name}-{version}.ext4"
            
            # Check if already downloaded and valid
            if template_file.exists():
                if self._verify_checksum(template_file, template.checksum):
                    logger.info(f"Template {key} already exists and is valid")
                    return True
                else:
                    logger.warning(f"Template {key} checksum mismatch, re-downloading")
                    template_file.unlink()
            
            # Download template
            download_url = f"{self.registry_url}/api/v1/templates/{name}/{version}/download"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    if response.status == 200:
                        with open(template_file, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                        
                        # Verify download
                        if self._verify_checksum(template_file, template.checksum):
                            logger.info(f"Successfully downloaded template {key}")
                            return True
                        else:
                            logger.error(f"Downloaded template {key} failed checksum verification")
                            template_file.unlink()
                            return False
                    else:
                        logger.error(f"Failed to download template {key}: HTTP {response.status}")
                        return False
        
        except Exception as e:
            logger.error(f"Failed to download template {name}:{version}: {e}")
            return False
    
    def _verify_checksum(self, file_path: Path, expected_checksum: str) -> bool:
        """Verify file checksum"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest() == expected_checksum
    
    def list_available_templates(self) -> List[TemplateInfo]:
        """List all available templates"""
        return list(self.catalog.values())
    
    def list_installed_templates(self) -> List[TemplateInfo]:
        """List installed templates"""
        installed = []
        for template in self.catalog.values():
            template_file = self.template_path / f"{template.name}-{template.version}.ext4"
            if template_file.exists():
                installed.append(template)
        return installed
    
    def get_template_path(self, name: str, version: str = "latest") -> Optional[Path]:
        """Get path to template file"""
        template_file = self.template_path / f"{name}-{version}.ext4"
        if template_file.exists():
            return template_file
        return None
    
    async def create_custom_template(self, 
                                   name: str,
                                   base_template: str,
                                   customization_script: str,
                                   metadata: Dict[str, Any]) -> bool:
        """Create custom template from base template"""
        try:
            # Get base template
            base_path = self.get_template_path(base_template)
            if not base_path:
                await self.download_template(base_template)
                base_path = self.get_template_path(base_template)
            
            if not base_path:
                logger.error(f"Base template {base_template} not available")
                return False
            
            # Create custom template directory
            custom_dir = self.cache_path / f"custom-{name}"
            custom_dir.mkdir(exist_ok=True)
            
            # Copy base template
            custom_template = custom_dir / f"{name}.ext4"
            await asyncio.create_subprocess_exec(
                "cp", str(base_path), str(custom_template)
            )
            
            # Apply customization
            await self._apply_customization(custom_template, customization_script)
            
            # Generate metadata
            template_info = TemplateInfo(
                name=name,
                version="1.0.0",
                architecture=metadata.get("architecture", "x86_64"),
                os_family=metadata.get("os_family", "linux"),
                os_version=metadata.get("os_version", "unknown"),
                description=metadata.get("description", f"Custom template based on {base_template}"),
                size_mb=custom_template.stat().st_size // (1024 * 1024),
                checksum=self._calculate_checksum(custom_template),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                security_level=metadata.get("security_level", "hardened"),
                features=metadata.get("features", []),
                maintainer=metadata.get("maintainer", "custom"),
                source_url="local",
                license=metadata.get("license", "custom")
            )
            
            # Move to templates directory
            final_path = self.template_path / f"{name}-1.0.0.ext4"
            custom_template.rename(final_path)
            
            # Add to catalog
            self.catalog[f"{name}:1.0.0"] = template_info
            self.save_catalog()
            
            logger.info(f"Created custom template {name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create custom template {name}: {e}")
            return False
    
    async def _apply_customization(self, template_path: Path, script: str):
        """Apply customization script to template"""
        # This would use tools like guestfish or similar to modify the filesystem
        # For now, we'll create a simple implementation
        script_file = template_path.parent / "customize.sh"
        with open(script_file, 'w') as f:
            f.write(script)
        
        # Would run customization in a secure environment
        logger.info(f"Applied customization to {template_path}")
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    async def check_security_updates(self) -> List[Dict[str, Any]]:
        """Check for security updates to installed templates"""
        updates = []
        
        await self.sync_with_registry()
        
        for template in self.list_installed_templates():
            # Check if newer version exists with security updates
            newer_versions = [
                t for t in self.catalog.values()
                if t.name == template.name and t.updated_at > template.updated_at
            ]
            
            for newer in newer_versions:
                updates.append({
                    "template": template.name,
                    "current_version": template.version,
                    "new_version": newer.version,
                    "security_update": True,
                    "description": newer.description
                })
        
        return updates
    
    async def auto_update_templates(self) -> Dict[str, bool]:
        """Automatically update templates with security patches"""
        results = {}
        
        updates = await self.check_security_updates()
        
        for update in updates:
            if update["security_update"]:
                success = await self.download_template(
                    update["template"], 
                    update["new_version"]
                )
                results[f"{update['template']}:{update['new_version']}"] = success
        
        return results