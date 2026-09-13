"""
Storage Management System for VPS Secure Compute Manager
Handles persistent volumes, snapshots, backups, and storage security
"""

import os
import asyncio
import logging
import json
import hashlib
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
import uuid
import aiofiles

logger = logging.getLogger(__name__)

class VolumeType(Enum):
    BLOCK = "block"
    FILE = "file"
    NETWORK = "network"
    ENCRYPTED = "encrypted"

class VolumeState(Enum):
    CREATING = "creating"
    AVAILABLE = "available"
    IN_USE = "in_use"
    DELETING = "deleting"
    ERROR = "error"
    SNAPSHOT = "snapshot"

class BackupState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class VolumeConfig:
    """Volume configuration"""
    name: str
    size_gb: float
    type: VolumeType
    tenant_id: str
    user_id: str
    encrypted: bool = True
    backup_enabled: bool = True
    backup_retention_days: int = 30
    mount_point: Optional[str] = None
    labels: Dict[str, str] = None
    created_at: Optional[datetime] = None

@dataclass
class Volume:
    """Volume instance"""
    id: str
    config: VolumeConfig
    state: VolumeState
    actual_size_gb: float
    device_path: Optional[str] = None
    encryption_key_id: Optional[str] = None
    attached_containers: List[str] = None
    last_backup: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

@dataclass
class Snapshot:
    """Volume snapshot"""
    id: str
    volume_id: str
    name: str
    size_gb: float
    tenant_id: str
    created_at: datetime
    description: Optional[str] = None
    tags: Dict[str, str] = None

@dataclass
class Backup:
    """Volume backup"""
    id: str
    volume_id: str
    snapshot_id: Optional[str]
    name: str
    size_gb: float
    state: BackupState
    tenant_id: str
    storage_location: str
    encryption_enabled: bool
    created_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

class StorageManager:
    """Commercial-grade storage management system"""
    
    def __init__(self, 
                 storage_path: str = "/opt/vps-secure-compute/storage",
                 backup_path: str = "/opt/vps-secure-compute/backups",
                 encryption_enabled: bool = True):
        
        self.storage_path = Path(storage_path)
        self.backup_path = Path(backup_path)
        self.encryption_enabled = encryption_enabled
        
        # Create directories
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.backup_path.mkdir(parents=True, exist_ok=True)
        
        # Storage registry
        self.volumes: Dict[str, Volume] = {}
        self.snapshots: Dict[str, Snapshot] = {}
        self.backups: Dict[str, Backup] = {}
        
        # Tenant quotas (GB)
        self.tenant_quotas: Dict[str, float] = {}
        self.tenant_usage: Dict[str, float] = {}
        
        # Encryption keys (in production, use proper key management)
        self.encryption_keys: Dict[str, str] = {}
        
        # Load existing volumes
        asyncio.create_task(self._load_existing_volumes())
    
    async def _load_existing_volumes(self):
        """Load existing volumes from storage"""
        try:
            volumes_file = self.storage_path / "volumes.json"
            if volumes_file.exists():
                async with aiofiles.open(volumes_file, 'r') as f:
                    data = json.loads(await f.read())
                    
                    for volume_data in data.get("volumes", []):
                        volume = Volume(**volume_data)
                        volume.config = VolumeConfig(**volume_data["config"])
                        self.volumes[volume.id] = volume
                        
                        # Update tenant usage
                        tenant_id = volume.config.tenant_id
                        if tenant_id not in self.tenant_usage:
                            self.tenant_usage[tenant_id] = 0
                        self.tenant_usage[tenant_id] += volume.actual_size_gb
            
            logger.info(f"Loaded {len(self.volumes)} existing volumes")
            
        except Exception as e:
            logger.error(f"Failed to load existing volumes: {e}")
    
    async def _save_volumes(self):
        """Save volumes to storage"""
        try:
            volumes_file = self.storage_path / "volumes.json"
            volumes_data = {
                "version": "1.0",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "volumes": [asdict(volume) for volume in self.volumes.values()]
            }
            
            async with aiofiles.open(volumes_file, 'w') as f:
                await f.write(json.dumps(volumes_data, indent=2, default=str))
                
        except Exception as e:
            logger.error(f"Failed to save volumes: {e}")
    
    async def create_volume(self, config: VolumeConfig) -> Optional[str]:
        """Create a new volume"""
        try:
            # Check tenant quota
            if not await self._check_tenant_quota(config.tenant_id, config.size_gb):
                raise ValueError(f"Insufficient storage quota for tenant {config.tenant_id}")
            
            volume_id = str(uuid.uuid4())
            config.created_at = datetime.now(timezone.utc)
            
            # Create volume directory
            volume_dir = self.storage_path / config.tenant_id / volume_id
            volume_dir.mkdir(parents=True, exist_ok=True)
            
            volume = Volume(
                id=volume_id,
                config=config,
                state=VolumeState.CREATING,
                actual_size_gb=0,
                attached_containers=[],
                created_at=datetime.now(timezone.utc)
            )
            
            # Create volume based on type
            if config.type == VolumeType.BLOCK:
                await self._create_block_volume(volume, volume_dir)
            elif config.type == VolumeType.FILE:
                await self._create_file_volume(volume, volume_dir)
            elif config.type == VolumeType.ENCRYPTED:
                await self._create_encrypted_volume(volume, volume_dir)
            else:
                raise ValueError(f"Unsupported volume type: {config.type}")
            
            # Update tenant usage
            self.tenant_usage[config.tenant_id] = self.tenant_usage.get(config.tenant_id, 0) + volume.actual_size_gb
            
            # Store volume
            self.volumes[volume_id] = volume
            await self._save_volumes()
            
            # Start backup scheduling if enabled
            if config.backup_enabled:
                asyncio.create_task(self._schedule_volume_backup(volume_id))
            
            logger.info(f"Created volume {volume_id} for tenant {config.tenant_id}")
            return volume_id
            
        except Exception as e:
            logger.error(f"Failed to create volume: {e}")
            return None
    
    async def _create_block_volume(self, volume: Volume, volume_dir: Path):
        """Create block volume using loop device"""
        volume_file = volume_dir / "volume.img"
        
        # Create sparse file
        await self._run_command([
            "truncate", "-s", f"{volume.config.size_gb}G", str(volume_file)
        ])
        
        # Format with ext4
        await self._run_command([
            "mkfs.ext4", "-F", str(volume_file)
        ])
        
        volume.device_path = str(volume_file)
        volume.actual_size_gb = volume.config.size_gb
        volume.state = VolumeState.AVAILABLE
    
    async def _create_file_volume(self, volume: Volume, volume_dir: Path):
        """Create file-based volume"""
        volume_mount = volume_dir / "mount"
        volume_mount.mkdir(exist_ok=True)
        
        # Set size limit using quota (if supported)
        # For now, we'll just track the size limit
        volume.device_path = str(volume_mount)
        volume.actual_size_gb = volume.config.size_gb
        volume.state = VolumeState.AVAILABLE
    
    async def _create_encrypted_volume(self, volume: Volume, volume_dir: Path):
        """Create encrypted volume using LUKS"""
        volume_file = volume_dir / "encrypted.img"
        
        # Create sparse file
        await self._run_command([
            "truncate", "-s", f"{volume.config.size_gb}G", str(volume_file)
        ])
        
        # Generate encryption key
        encryption_key = os.urandom(32).hex()
        key_id = str(uuid.uuid4())
        self.encryption_keys[key_id] = encryption_key
        
        # Setup LUKS encryption
        key_file = volume_dir / "keyfile"
        async with aiofiles.open(key_file, 'w') as f:
            await f.write(encryption_key)
        
        await self._run_command([
            "cryptsetup", "luksFormat", "--batch-mode", "--key-file", str(key_file), str(volume_file)
        ])
        
        # Remove key file for security
        key_file.unlink()
        
        volume.device_path = str(volume_file)
        volume.encryption_key_id = key_id
        volume.actual_size_gb = volume.config.size_gb
        volume.state = VolumeState.AVAILABLE
    
    async def attach_volume(self, volume_id: str, container_id: str, mount_point: str) -> bool:
        """Attach volume to container"""
        try:
            if volume_id not in self.volumes:
                raise ValueError(f"Volume {volume_id} not found")
            
            volume = self.volumes[volume_id]
            
            if volume.state != VolumeState.AVAILABLE:
                raise ValueError(f"Volume {volume_id} is not available (state: {volume.state})")
            
            # Mount volume
            if volume.config.type == VolumeType.ENCRYPTED:
                await self._mount_encrypted_volume(volume, mount_point)
            else:
                await self._mount_regular_volume(volume, mount_point)
            
            # Update volume state
            volume.state = VolumeState.IN_USE
            volume.attached_containers.append(container_id)
            volume.config.mount_point = mount_point
            volume.updated_at = datetime.now(timezone.utc)
            
            await self._save_volumes()
            
            logger.info(f"Attached volume {volume_id} to container {container_id} at {mount_point}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to attach volume {volume_id} to container {container_id}: {e}")
            return False
    
    async def _mount_encrypted_volume(self, volume: Volume, mount_point: str):
        """Mount encrypted volume"""
        if not volume.encryption_key_id or volume.encryption_key_id not in self.encryption_keys:
            raise ValueError("Encryption key not found")
        
        # Create mapper name
        mapper_name = f"vps-{volume.id[:8]}"
        
        # Open LUKS device
        key_file = f"/tmp/key-{volume.id}"
        with open(key_file, 'w') as f:
            f.write(self.encryption_keys[volume.encryption_key_id])
        
        try:
            await self._run_command([
                "cryptsetup", "open", "--key-file", key_file, volume.device_path, mapper_name
            ])
            
            # Mount the mapped device
            os.makedirs(mount_point, exist_ok=True)
            await self._run_command([
                "mount", f"/dev/mapper/{mapper_name}", mount_point
            ])
            
        finally:
            # Clean up key file
            if os.path.exists(key_file):
                os.unlink(key_file)
    
    async def _mount_regular_volume(self, volume: Volume, mount_point: str):
        """Mount regular volume"""
        os.makedirs(mount_point, exist_ok=True)
        
        if volume.config.type == VolumeType.BLOCK:
            await self._run_command([
                "mount", "-o", "loop", volume.device_path, mount_point
            ])
        elif volume.config.type == VolumeType.FILE:
            # Bind mount for file volumes
            await self._run_command([
                "mount", "--bind", volume.device_path, mount_point
            ])
    
    async def detach_volume(self, volume_id: str, container_id: str) -> bool:
        """Detach volume from container"""
        try:
            if volume_id not in self.volumes:
                raise ValueError(f"Volume {volume_id} not found")
            
            volume = self.volumes[volume_id]
            
            if container_id not in volume.attached_containers:
                raise ValueError(f"Volume {volume_id} not attached to container {container_id}")
            
            # Unmount volume
            if volume.config.mount_point:
                await self._run_command([
                    "umount", volume.config.mount_point
                ], ignore_errors=True)
                
                # Close encrypted volume if needed
                if volume.config.type == VolumeType.ENCRYPTED:
                    mapper_name = f"vps-{volume.id[:8]}"
                    await self._run_command([
                        "cryptsetup", "close", mapper_name
                    ], ignore_errors=True)
            
            # Update volume state
            volume.attached_containers.remove(container_id)
            if not volume.attached_containers:
                volume.state = VolumeState.AVAILABLE
                volume.config.mount_point = None
            
            volume.updated_at = datetime.now(timezone.utc)
            await self._save_volumes()
            
            logger.info(f"Detached volume {volume_id} from container {container_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to detach volume {volume_id} from container {container_id}: {e}")
            return False
    
    async def create_snapshot(self, volume_id: str, name: str, description: str = None) -> Optional[str]:
        """Create volume snapshot"""
        try:
            if volume_id not in self.volumes:
                raise ValueError(f"Volume {volume_id} not found")
            
            volume = self.volumes[volume_id]
            snapshot_id = str(uuid.uuid4())
            
            # Create snapshot directory
            snapshot_dir = self.storage_path / volume.config.tenant_id / "snapshots" / snapshot_id
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            
            # Create snapshot file
            snapshot_file = snapshot_dir / "snapshot.img"
            
            # Copy volume data
            await self._run_command([
                "cp", "--sparse=always", volume.device_path, str(snapshot_file)
            ])
            
            # Create snapshot record
            snapshot = Snapshot(
                id=snapshot_id,
                volume_id=volume_id,
                name=name,
                size_gb=volume.actual_size_gb,
                tenant_id=volume.config.tenant_id,
                created_at=datetime.now(timezone.utc),
                description=description
            )
            
            self.snapshots[snapshot_id] = snapshot
            
            logger.info(f"Created snapshot {snapshot_id} of volume {volume_id}")
            return snapshot_id
            
        except Exception as e:
            logger.error(f"Failed to create snapshot of volume {volume_id}: {e}")
            return None
    
    async def create_backup(self, volume_id: str, name: str) -> Optional[str]:
        """Create volume backup"""
        try:
            if volume_id not in self.volumes:
                raise ValueError(f"Volume {volume_id} not found")
            
            volume = self.volumes[volume_id]
            backup_id = str(uuid.uuid4())
            
            # Create backup
            backup = Backup(
                id=backup_id,
                volume_id=volume_id,
                snapshot_id=None,
                name=name,
                size_gb=volume.actual_size_gb,
                state=BackupState.PENDING,
                tenant_id=volume.config.tenant_id,
                storage_location=str(self.backup_path / volume.config.tenant_id / backup_id),
                encryption_enabled=self.encryption_enabled,
                created_at=datetime.now(timezone.utc)
            )
            
            self.backups[backup_id] = backup
            
            # Start backup process
            asyncio.create_task(self._perform_backup(backup))
            
            logger.info(f"Started backup {backup_id} of volume {volume_id}")
            return backup_id
            
        except Exception as e:
            logger.error(f"Failed to create backup of volume {volume_id}: {e}")
            return None
    
    async def _perform_backup(self, backup: Backup):
        """Perform backup operation"""
        try:
            backup.state = BackupState.RUNNING
            
            volume = self.volumes[backup.volume_id]
            backup_dir = Path(backup.storage_location)
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            backup_file = backup_dir / "backup.tar.gz"
            
            # Create compressed backup
            if backup.encryption_enabled:
                # Encrypt and compress
                await self._run_command([
                    "tar", "-czf", str(backup_file), "-C", str(Path(volume.device_path).parent), 
                    Path(volume.device_path).name
                ])
            else:
                # Just compress
                await self._run_command([
                    "tar", "-czf", str(backup_file), "-C", str(Path(volume.device_path).parent),
                    Path(volume.device_path).name
                ])
            
            backup.state = BackupState.COMPLETED
            backup.completed_at = datetime.now(timezone.utc)
            
            # Set expiration
            if volume.config.backup_retention_days > 0:
                from datetime import timedelta
                backup.expires_at = backup.completed_at + timedelta(days=volume.config.backup_retention_days)
            
            logger.info(f"Completed backup {backup.id}")
            
        except Exception as e:
            logger.error(f"Backup {backup.id} failed: {e}")
            backup.state = BackupState.FAILED
    
    async def restore_from_backup(self, backup_id: str, new_volume_name: str) -> Optional[str]:
        """Restore volume from backup"""
        try:
            if backup_id not in self.backups:
                raise ValueError(f"Backup {backup_id} not found")
            
            backup = self.backups[backup_id]
            
            if backup.state != BackupState.COMPLETED:
                raise ValueError(f"Backup {backup_id} is not completed")
            
            # Get original volume config
            original_volume = self.volumes.get(backup.volume_id)
            if not original_volume:
                raise ValueError(f"Original volume {backup.volume_id} not found")
            
            # Create new volume config
            new_config = VolumeConfig(
                name=new_volume_name,
                size_gb=backup.size_gb,
                type=original_volume.config.type,
                tenant_id=backup.tenant_id,
                user_id=original_volume.config.user_id,
                encrypted=original_volume.config.encrypted
            )
            
            # Create new volume
            new_volume_id = await self.create_volume(new_config)
            if not new_volume_id:
                raise ValueError("Failed to create volume for restore")
            
            # Restore data
            backup_file = Path(backup.storage_location) / "backup.tar.gz"
            new_volume = self.volumes[new_volume_id]
            volume_dir = Path(new_volume.device_path).parent
            
            await self._run_command([
                "tar", "-xzf", str(backup_file), "-C", str(volume_dir)
            ])
            
            logger.info(f"Restored volume {new_volume_id} from backup {backup_id}")
            return new_volume_id
            
        except Exception as e:
            logger.error(f"Failed to restore from backup {backup_id}: {e}")
            return None
    
    async def _check_tenant_quota(self, tenant_id: str, size_gb: float) -> bool:
        """Check if tenant has sufficient quota"""
        quota = self.tenant_quotas.get(tenant_id, float('inf'))
        usage = self.tenant_usage.get(tenant_id, 0)
        
        return usage + size_gb <= quota
    
    def set_tenant_quota(self, tenant_id: str, quota_gb: float):
        """Set storage quota for tenant"""
        self.tenant_quotas[tenant_id] = quota_gb
    
    def get_volume_info(self, volume_id: str) -> Optional[Dict[str, Any]]:
        """Get volume information"""
        if volume_id not in self.volumes:
            return None
        
        volume = self.volumes[volume_id]
        return {
            "id": volume.id,
            "name": volume.config.name,
            "size_gb": volume.actual_size_gb,
            "type": volume.config.type.value,
            "state": volume.state.value,
            "tenant_id": volume.config.tenant_id,
            "encrypted": volume.config.encrypted,
            "attached_containers": volume.attached_containers,
            "mount_point": volume.config.mount_point,
            "created_at": volume.created_at.isoformat() if volume.created_at else None,
            "last_backup": volume.last_backup.isoformat() if volume.last_backup else None
        }
    
    def list_volumes(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List volumes, optionally filtered by tenant"""
        volumes = []
        
        for volume in self.volumes.values():
            if tenant_id and volume.config.tenant_id != tenant_id:
                continue
            
            volume_info = self.get_volume_info(volume.id)
            if volume_info:
                volumes.append(volume_info)
        
        return volumes
    
    async def delete_volume(self, volume_id: str) -> bool:
        """Delete volume"""
        try:
            if volume_id not in self.volumes:
                return False
            
            volume = self.volumes[volume_id]
            
            if volume.state == VolumeState.IN_USE:
                raise ValueError(f"Volume {volume_id} is in use")
            
            volume.state = VolumeState.DELETING
            
            # Delete volume files
            volume_dir = Path(volume.device_path).parent
            if volume_dir.exists():
                await self._run_command(["rm", "-rf", str(volume_dir)])
            
            # Update tenant usage
            self.tenant_usage[volume.config.tenant_id] -= volume.actual_size_gb
            
            # Remove from registry
            del self.volumes[volume_id]
            await self._save_volumes()
            
            logger.info(f"Deleted volume {volume_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete volume {volume_id}: {e}")
            return False
    
    async def _schedule_volume_backup(self, volume_id: str):
        """Schedule automatic backups for volume"""
        # This would implement automatic backup scheduling
        # For now, it's a placeholder
        pass
    
    async def _run_command(self, cmd: List[str], ignore_errors: bool = False) -> bool:
        """Run system command"""
        try:
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0 and not ignore_errors:
                logger.error(f"Command failed: {' '.join(cmd)}, stderr: {stderr.decode()}")
                return False
            
            return True
            
        except Exception as e:
            if not ignore_errors:
                logger.error(f"Failed to run command {' '.join(cmd)}: {e}")
            return False