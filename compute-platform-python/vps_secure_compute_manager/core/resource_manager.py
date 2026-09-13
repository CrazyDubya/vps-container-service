"""
Resource Manager with Quota Enforcement
Manages resource allocation and enforces tenant/user quotas
"""

from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from dataclasses import dataclass
import logging

from ..iam.models import User, Tenant, TenantQuota, UserQuota, Container, ResourceType, AuditLog
from .exceptions import ResourceQuotaExceeded, TenantIsolationError, AuthorizationError

logger = logging.getLogger(__name__)

@dataclass
class ResourceRequest:
    """Resource allocation request"""
    user_id: str
    tenant_id: str
    resource_type: str
    amount: float
    container_name: str = None
    backend_type: str = None

@dataclass
class QuotaInfo:
    """Quota information"""
    resource_type: str
    max_value: float
    current_value: float
    available: float
    utilization_percent: float

class ResourceManager:
    """Manages resource allocation and quota enforcement"""
    
    def __init__(self):
        self.resource_weights = {
            ResourceType.FIRECRACKER_VM.value: 1.0,
            ResourceType.LXC_CONTAINER.value: 2.0,  # LXC containers are "heavier"
            ResourceType.MEMORY_GB.value: 1.0,
            ResourceType.CPU_CORES.value: 1.0,
            ResourceType.GPU_HOURS.value: 10.0,     # GPU time is expensive
            ResourceType.STORAGE_GB.value: 0.1,
            ResourceType.NETWORK_MBPS.value: 0.01
        }
    
    def check_resource_availability(self, db: Session, request: ResourceRequest) -> bool:
        """Check if requested resources are available within quotas"""
        try:
            # Check user quota
            user_available = self._check_user_quota(db, request)
            if not user_available:
                return False
            
            # Check tenant quota
            tenant_available = self._check_tenant_quota(db, request)
            if not tenant_available:
                return False
            
            # Additional checks for specific resource types
            if request.resource_type in [ResourceType.FIRECRACKER_VM.value, ResourceType.LXC_CONTAINER.value]:
                return self._check_container_limits(db, request)
            
            return True
            
        except Exception as e:
            logger.error(f"Resource availability check failed: {str(e)}")
            return False
    
    def allocate_resources(self, db: Session, request: ResourceRequest) -> Dict[str, Any]:
        """Allocate resources and update quotas"""
        try:
            # Verify availability first
            if not self.check_resource_availability(db, request):
                raise ResourceQuotaExceeded(
                    f"Insufficient {request.resource_type} quota for user {request.user_id}",
                    quota_type=request.resource_type
                )
            
            # Update user quota
            self._update_user_quota(db, request.user_id, request.resource_type, request.amount)
            
            # Update tenant quota
            self._update_tenant_quota(db, request.tenant_id, request.resource_type, request.amount)
            
            # Log resource allocation
            self._log_resource_allocation(db, request, "allocated")
            
            db.commit()
            
            return {
                "success": True,
                "allocated_amount": request.amount,
                "resource_type": request.resource_type,
                "user_id": request.user_id,
                "tenant_id": request.tenant_id
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Resource allocation failed: {str(e)}")
            raise
    
    def deallocate_resources(self, db: Session, request: ResourceRequest) -> Dict[str, Any]:
        """Deallocate resources and update quotas"""
        try:
            # Update user quota (subtract allocation)
            self._update_user_quota(db, request.user_id, request.resource_type, -request.amount)
            
            # Update tenant quota (subtract allocation)
            self._update_tenant_quota(db, request.tenant_id, request.resource_type, -request.amount)
            
            # Log resource deallocation
            self._log_resource_allocation(db, request, "deallocated")
            
            db.commit()
            
            return {
                "success": True,
                "deallocated_amount": request.amount,
                "resource_type": request.resource_type,
                "user_id": request.user_id,
                "tenant_id": request.tenant_id
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Resource deallocation failed: {str(e)}")
            raise
    
    def get_user_quota_info(self, db: Session, user_id: str) -> List[QuotaInfo]:
        """Get quota information for user"""
        try:
            quotas = db.query(UserQuota).filter(UserQuota.user_id == user_id).all()
            
            quota_info = []
            for quota in quotas:
                available = quota.max_value - quota.current_value
                utilization = (quota.current_value / quota.max_value * 100) if quota.max_value > 0 else 0
                
                quota_info.append(QuotaInfo(
                    resource_type=quota.resource_type,
                    max_value=quota.max_value,
                    current_value=quota.current_value,
                    available=available,
                    utilization_percent=utilization
                ))
            
            return quota_info
            
        except Exception as e:
            logger.error(f"Failed to get user quota info: {str(e)}")
            raise
    
    def get_tenant_quota_info(self, db: Session, tenant_id: str) -> List[QuotaInfo]:
        """Get quota information for tenant"""
        try:
            quotas = db.query(TenantQuota).filter(TenantQuota.tenant_id == tenant_id).all()
            
            quota_info = []
            for quota in quotas:
                available = quota.max_value - quota.current_value
                utilization = (quota.current_value / quota.max_value * 100) if quota.max_value > 0 else 0
                
                quota_info.append(QuotaInfo(
                    resource_type=quota.resource_type,
                    max_value=quota.max_value,
                    current_value=quota.current_value,
                    available=available,
                    utilization_percent=utilization
                ))
            
            return quota_info
            
        except Exception as e:
            logger.error(f"Failed to get tenant quota info: {str(e)}")
            raise
    
    def update_quota_limits(self, db: Session, user_context: Dict[str, Any], 
                           target_type: str, target_id: str, quotas: Dict[str, float]):
        """Update quota limits (admin function)"""
        try:
            # Verify admin permissions
            from ..iam.auth import AuthorizationManager
            auth_manager = AuthorizationManager()
            
            if not auth_manager.check_permission(user_context, "update", "quotas"):
                raise AuthorizationError("Insufficient permissions to update quotas")
            
            if target_type == "user":
                self._update_user_quota_limits(db, target_id, quotas)
            elif target_type == "tenant":
                self._update_tenant_quota_limits(db, target_id, quotas)
            else:
                raise ValueError(f"Invalid target type: {target_type}")
            
            # Log quota update
            audit_log = AuditLog(
                tenant_id=user_context.get("tenant_id"),
                user_id=user_context["user_id"],
                action="quota_update",
                resource_type=target_type,
                resource_id=target_id,
                details=f"Updated quotas: {quotas}",
                severity="info",
                status="success"
            )
            db.add(audit_log)
            
            db.commit()
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update quota limits: {str(e)}")
            raise
    
    def calculate_resource_cost(self, resource_type: str, amount: float, duration_hours: float = 1.0) -> float:
        """Calculate cost for resource usage"""
        base_cost = amount * self.resource_weights.get(resource_type, 1.0)
        
        # Time-based resources (like GPU hours) include duration
        if resource_type == ResourceType.GPU_HOURS.value:
            return base_cost * duration_hours
        
        return base_cost
    
    def _check_user_quota(self, db: Session, request: ResourceRequest) -> bool:
        """Check if user has sufficient quota"""
        quota = db.query(UserQuota).filter(
            UserQuota.user_id == request.user_id,
            UserQuota.resource_type == request.resource_type
        ).first()
        
        if not quota:
            logger.warning(f"No quota found for user {request.user_id}, resource {request.resource_type}")
            return False
        
        available = quota.max_value - quota.current_value
        return available >= request.amount
    
    def _check_tenant_quota(self, db: Session, request: ResourceRequest) -> bool:
        """Check if tenant has sufficient quota"""
        quota = db.query(TenantQuota).filter(
            TenantQuota.tenant_id == request.tenant_id,
            TenantQuota.resource_type == request.resource_type
        ).first()
        
        if not quota:
            logger.warning(f"No quota found for tenant {request.tenant_id}, resource {request.resource_type}")
            return False
        
        available = quota.max_value - quota.current_value
        return available >= request.amount
    
    def _check_container_limits(self, db: Session, request: ResourceRequest) -> bool:
        """Check container-specific limits"""
        # Count existing containers for user
        container_count = db.query(Container).filter(
            Container.user_id == request.user_id,
            Container.backend_type == request.backend_type
        ).count()
        
        # Check if user can create another container
        quota = db.query(UserQuota).filter(
            UserQuota.user_id == request.user_id,
            UserQuota.resource_type == request.resource_type
        ).first()
        
        if quota:
            return container_count < quota.max_value
        
        return False
    
    def _update_user_quota(self, db: Session, user_id: str, resource_type: str, amount: float):
        """Update user quota current value"""
        quota = db.query(UserQuota).filter(
            UserQuota.user_id == user_id,
            UserQuota.resource_type == resource_type
        ).first()
        
        if quota:
            quota.current_value += amount
            # Ensure current value doesn't go negative
            quota.current_value = max(0, quota.current_value)
    
    def _update_tenant_quota(self, db: Session, tenant_id: str, resource_type: str, amount: float):
        """Update tenant quota current value"""
        quota = db.query(TenantQuota).filter(
            TenantQuota.tenant_id == tenant_id,
            TenantQuota.resource_type == resource_type
        ).first()
        
        if quota:
            quota.current_value += amount
            # Ensure current value doesn't go negative
            quota.current_value = max(0, quota.current_value)
    
    def _update_user_quota_limits(self, db: Session, user_id: str, quotas: Dict[str, float]):
        """Update user quota limits"""
        for resource_type, max_value in quotas.items():
            quota = db.query(UserQuota).filter(
                UserQuota.user_id == user_id,
                UserQuota.resource_type == resource_type
            ).first()
            
            if quota:
                quota.max_value = max_value
            else:
                # Create new quota if it doesn't exist
                new_quota = UserQuota(
                    user_id=user_id,
                    resource_type=resource_type,
                    max_value=max_value
                )
                db.add(new_quota)
    
    def _update_tenant_quota_limits(self, db: Session, tenant_id: str, quotas: Dict[str, float]):
        """Update tenant quota limits"""
        for resource_type, max_value in quotas.items():
            quota = db.query(TenantQuota).filter(
                TenantQuota.tenant_id == tenant_id,
                TenantQuota.resource_type == resource_type
            ).first()
            
            if quota:
                quota.max_value = max_value
            else:
                # Create new quota if it doesn't exist
                new_quota = TenantQuota(
                    tenant_id=tenant_id,
                    resource_type=resource_type,
                    max_value=max_value
                )
                db.add(new_quota)
    
    def _log_resource_allocation(self, db: Session, request: ResourceRequest, action: str):
        """Log resource allocation/deallocation"""
        audit_log = AuditLog(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            action=f"resource_{action}",
            resource_type="quota",
            details=f"{action.title()} {request.amount} {request.resource_type}",
            severity="info",
            status="success"
        )
        db.add(audit_log)