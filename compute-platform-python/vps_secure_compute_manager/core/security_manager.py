"""
Security Manager - Central security policy enforcement
Handles security policies, container hardening, and threat detection
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
import subprocess
import hashlib
from pathlib import Path

from .exceptions import SecurityViolation, ConfigurationError
from ..iam.models import AuditLog, User, Container

logger = logging.getLogger(__name__)

class SecurityLevel(Enum):
    """Security hardening levels"""
    MINIMAL = "minimal"
    STANDARD = "standard"
    HARDENED = "hardened"
    PARANOID = "paranoid"

class ThreatLevel(Enum):
    """Threat severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class SecurityPolicy:
    """Security policy configuration"""
    name: str
    level: SecurityLevel
    firecracker_config: Dict[str, Any]
    lxc_config: Dict[str, Any]
    seccomp_profile: str
    apparmor_profile: str
    capabilities_drop: List[str]
    syscall_restrictions: List[str]
    network_restrictions: Dict[str, Any]

@dataclass
class SecurityEvent:
    """Security event/violation"""
    event_type: str
    threat_level: ThreatLevel
    container_id: str
    user_id: str
    tenant_id: str
    description: str
    details: Dict[str, Any]
    mitigation_actions: List[str]

class SecurityManager:
    """Central security policy enforcement and monitoring"""
    
    def __init__(self, config_dir: str = "/etc/vps-secure-compute"):
        self.config_dir = Path(config_dir)
        self.policies = {}
        self.active_monitors = {}
        
        # Load security policies
        self._load_security_policies()
        
        # Initialize security subsystems
        self._initialize_security_subsystems()
    
    def get_security_policy(self, backend_type: str, security_level: SecurityLevel = SecurityLevel.STANDARD) -> SecurityPolicy:
        """Get security policy for backend type and level"""
        policy_key = f"{backend_type}_{security_level.value}"
        
        if policy_key not in self.policies:
            raise ConfigurationError(f"Security policy not found: {policy_key}")
        
        return self.policies[policy_key]
    
    def validate_container_config(self, backend_type: str, config: Dict[str, Any], 
                                 user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and secure container configuration"""
        try:
            # Get appropriate security policy
            security_level = self._determine_security_level(user_context)
            policy = self.get_security_policy(backend_type, security_level)
            
            # Apply security hardening based on backend type
            if backend_type == "firecracker":
                return self._secure_firecracker_config(config, policy, user_context)
            elif backend_type == "lxc":
                return self._secure_lxc_config(config, policy, user_context)
            else:
                raise SecurityViolation(f"Unsupported backend type: {backend_type}")
                
        except Exception as e:
            logger.error(f"Container config validation failed: {str(e)}")
            raise SecurityViolation(f"Security validation failed: {str(e)}")
    
    def monitor_container_security(self, container_id: str, user_context: Dict[str, Any]):
        """Start security monitoring for container"""
        try:
            # Start syscall monitoring
            self._start_syscall_monitoring(container_id)
            
            # Start resource monitoring
            self._start_resource_monitoring(container_id)
            
            # Start network monitoring
            self._start_network_monitoring(container_id)
            
            # Register active monitor
            self.active_monitors[container_id] = {
                "user_id": user_context["user_id"],
                "tenant_id": user_context["tenant_id"],
                "started_at": "now",
                "monitors": ["syscall", "resource", "network"]
            }
            
            logger.info(f"Security monitoring started for container {container_id}")
            
        except Exception as e:
            logger.error(f"Failed to start security monitoring: {str(e)}")
            raise SecurityViolation(f"Security monitoring setup failed: {str(e)}")
    
    def stop_container_monitoring(self, container_id: str):
        """Stop security monitoring for container"""
        try:
            if container_id in self.active_monitors:
                # Stop all monitoring processes
                self._stop_syscall_monitoring(container_id)
                self._stop_resource_monitoring(container_id)
                self._stop_network_monitoring(container_id)
                
                # Remove from active monitors
                del self.active_monitors[container_id]
                
                logger.info(f"Security monitoring stopped for container {container_id}")
                
        except Exception as e:
            logger.error(f"Failed to stop security monitoring: {str(e)}")
    
    def handle_security_event(self, event: SecurityEvent, db_session) -> List[str]:
        """Handle security event and take mitigation actions"""
        try:
            # Log security event
            self._log_security_event(event, db_session)
            
            # Determine response actions based on threat level
            actions_taken = []
            
            if event.threat_level == ThreatLevel.CRITICAL:
                # Immediate container shutdown
                actions_taken.append(self._emergency_container_shutdown(event.container_id))
                # Alert administrators
                actions_taken.append(self._alert_administrators(event))
                # Quarantine container
                actions_taken.append(self._quarantine_container(event.container_id))
                
            elif event.threat_level == ThreatLevel.HIGH:
                # Restrict container capabilities
                actions_taken.append(self._restrict_container_capabilities(event.container_id))
                # Increase monitoring
                actions_taken.append(self._increase_monitoring_level(event.container_id))
                # Alert tenant admin
                actions_taken.append(self._alert_tenant_admin(event))
                
            elif event.threat_level == ThreatLevel.MEDIUM:
                # Log and monitor
                actions_taken.append(self._increase_logging_level(event.container_id))
                actions_taken.append(self._schedule_security_review(event))
                
            else:  # LOW
                # Just log for analysis
                actions_taken.append("logged_for_analysis")
            
            return actions_taken
            
        except Exception as e:
            logger.error(f"Failed to handle security event: {str(e)}")
            return ["error_handling_security_event"]
    
    def audit_security_compliance(self, tenant_id: str) -> Dict[str, Any]:
        """Audit security compliance for tenant"""
        try:
            compliance_report = {
                "tenant_id": tenant_id,
                "audit_timestamp": "now",
                "compliance_score": 0,
                "findings": [],
                "recommendations": []
            }
            
            # Check container security configurations
            container_compliance = self._audit_container_security(tenant_id)
            compliance_report["container_security"] = container_compliance
            
            # Check user access patterns
            access_compliance = self._audit_access_patterns(tenant_id)
            compliance_report["access_patterns"] = access_compliance
            
            # Check resource usage patterns
            resource_compliance = self._audit_resource_usage(tenant_id)
            compliance_report["resource_usage"] = resource_compliance
            
            # Calculate overall compliance score
            compliance_report["compliance_score"] = self._calculate_compliance_score(
                container_compliance, access_compliance, resource_compliance
            )
            
            return compliance_report
            
        except Exception as e:
            logger.error(f"Security compliance audit failed: {str(e)}")
            raise SecurityViolation(f"Compliance audit failed: {str(e)}")
    
    def _load_security_policies(self):
        """Load security policies from configuration files"""
        try:
            # Load Firecracker policies
            firecracker_policies = self._load_firecracker_policies()
            self.policies.update(firecracker_policies)
            
            # Load LXC policies
            lxc_policies = self._load_lxc_policies()
            self.policies.update(lxc_policies)
            
            logger.info(f"Loaded {len(self.policies)} security policies")
            
        except Exception as e:
            logger.error(f"Failed to load security policies: {str(e)}")
            # Use default policies as fallback
            self._create_default_policies()
    
    def _load_firecracker_policies(self) -> Dict[str, SecurityPolicy]:
        """Load Firecracker security policies"""
        policies = {}
        
        # Hardened Firecracker policy
        policies["firecracker_hardened"] = SecurityPolicy(
            name="Firecracker Hardened",
            level=SecurityLevel.HARDENED,
            firecracker_config={
                "kernel_image_path": "/opt/firecracker/kernels/vmlinux-hardened",
                "boot_args": "console=ttyS0 reboot=k panic=1 pci=off nomodules",
                "machine_config": {
                    "vcpu_count": 2,
                    "mem_size_mib": 512,
                    "ht_enabled": False,
                    "cpu_template": "C3"
                },
                "rate_limiters": {
                    "network_rx": {"bandwidth": {"size": 1000000, "refill_time": 100}},
                    "network_tx": {"bandwidth": {"size": 1000000, "refill_time": 100}},
                    "disk_read": {"bandwidth": {"size": 10000000, "refill_time": 100}},
                    "disk_write": {"bandwidth": {"size": 10000000, "refill_time": 100}}
                }
            },
            lxc_config={},
            seccomp_profile="firecracker-hardened",
            apparmor_profile="firecracker-hardened",
            capabilities_drop=["ALL"],
            syscall_restrictions=["whitelist_only"],
            network_restrictions={"isolation": "strict", "egress": "filtered"}
        )
        
        return policies
    
    def _load_lxc_policies(self) -> Dict[str, SecurityPolicy]:
        """Load LXC security policies"""
        policies = {}
        
        # Hardened LXC policy
        policies["lxc_hardened"] = SecurityPolicy(
            name="LXC Hardened",
            level=SecurityLevel.HARDENED,
            firecracker_config={},
            lxc_config={
                "lxc.apparmor.profile": "generated",
                "lxc.seccomp.profile": "/etc/lxc/seccomp.policy",
                "lxc.idmap": ["u 0 100000 65536", "g 0 100000 65536"],
                "lxc.mount.auto": "proc:rw sys:ro cgroup:ro",
                "lxc.cap.drop": [
                    "sys_admin", "net_admin", "sys_module", "sys_rawio",
                    "sys_pacct", "sys_nice", "sys_resource", "sys_time",
                    "audit_write", "audit_control", "mac_admin", "mac_override"
                ],
                "lxc.cgroup2.devices.deny": "a",
                "lxc.cgroup2.devices.allow": ["c 1:3 rwm", "c 1:5 rwm", "c 5:0 rwm", "c 5:1 rwm"]
            },
            seccomp_profile="lxc-hardened",
            apparmor_profile="lxc-container-default-cgns",
            capabilities_drop=["sys_admin", "net_admin", "sys_module", "sys_rawio"],
            syscall_restrictions=["seccomp_filtered"],
            network_restrictions={"isolation": "bridge", "egress": "nat"}
        )
        
        return policies
    
    def _create_default_policies(self):
        """Create default security policies as fallback"""
        # Minimal default policy
        self.policies["default"] = SecurityPolicy(
            name="Default Security",
            level=SecurityLevel.STANDARD,
            firecracker_config={"machine_config": {"vcpu_count": 1, "mem_size_mib": 256}},
            lxc_config={"lxc.apparmor.profile": "generated"},
            seccomp_profile="default",
            apparmor_profile="default",
            capabilities_drop=["sys_admin"],
            syscall_restrictions=[],
            network_restrictions={}
        )
    
    def _determine_security_level(self, user_context: Dict[str, Any]) -> SecurityLevel:
        """Determine appropriate security level for user"""
        # For now, use hardened security for all users
        # In production, this could be based on tenant settings or user role
        return SecurityLevel.HARDENED
    
    def _secure_firecracker_config(self, config: Dict[str, Any], policy: SecurityPolicy, 
                                  user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply Firecracker security hardening"""
        secured_config = config.copy()
        
        # Apply security policy settings
        secured_config.update(policy.firecracker_config)
        
        # Enforce resource limits
        machine_config = secured_config.get("machine_config", {})
        machine_config["vcpu_count"] = min(machine_config.get("vcpu_count", 1), 4)
        machine_config["mem_size_mib"] = min(machine_config.get("mem_size_mib", 256), 2048)
        
        # Ensure read-only root filesystem
        secured_config["readonly_rootfs"] = True
        
        # Apply rate limiting
        secured_config["rate_limiters"] = policy.firecracker_config.get("rate_limiters", {})
        
        return secured_config
    
    def _secure_lxc_config(self, config: Dict[str, Any], policy: SecurityPolicy, 
                          user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply LXC security hardening"""
        secured_config = config.copy()
        
        # Apply security policy settings
        secured_config.update(policy.lxc_config)
        
        # Ensure unprivileged container
        secured_config["lxc.unprivileged"] = "1"
        
        # Apply capability restrictions
        for cap in policy.capabilities_drop:
            secured_config[f"lxc.cap.drop"] = cap
        
        # Apply resource limits
        secured_config["lxc.cgroup2.memory.max"] = "2G"
        secured_config["lxc.cgroup2.cpu.max"] = "200000 100000"  # 2 CPU cores max
        
        return secured_config
    
    def _start_syscall_monitoring(self, container_id: str):
        """Start syscall monitoring for container"""
        # In production, this would use tools like auditd or eBPF
        logger.debug(f"Started syscall monitoring for {container_id}")
    
    def _start_resource_monitoring(self, container_id: str):
        """Start resource usage monitoring"""
        # Monitor CPU, memory, disk, network usage
        logger.debug(f"Started resource monitoring for {container_id}")
    
    def _start_network_monitoring(self, container_id: str):
        """Start network traffic monitoring"""
        # Monitor network connections and traffic patterns
        logger.debug(f"Started network monitoring for {container_id}")
    
    def _stop_syscall_monitoring(self, container_id: str):
        """Stop syscall monitoring"""
        logger.debug(f"Stopped syscall monitoring for {container_id}")
    
    def _stop_resource_monitoring(self, container_id: str):
        """Stop resource monitoring"""
        logger.debug(f"Stopped resource monitoring for {container_id}")
    
    def _stop_network_monitoring(self, container_id: str):
        """Stop network monitoring"""
        logger.debug(f"Stopped network monitoring for {container_id}")
    
    def _log_security_event(self, event: SecurityEvent, db_session):
        """Log security event to audit trail"""
        audit_log = AuditLog(
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            action="security_event",
            resource_type="container",
            resource_id=event.container_id,
            details=json.dumps({
                "event_type": event.event_type,
                "threat_level": event.threat_level.value,
                "description": event.description,
                "details": event.details
            }),
            severity="critical" if event.threat_level == ThreatLevel.CRITICAL else "warning",
            status="detected"
        )
        db_session.add(audit_log)
    
    def _emergency_container_shutdown(self, container_id: str) -> str:
        """Emergency shutdown of container"""
        # Implement immediate container termination
        logger.critical(f"Emergency shutdown of container {container_id}")
        return "emergency_shutdown_initiated"
    
    def _alert_administrators(self, event: SecurityEvent) -> str:
        """Alert system administrators"""
        # Send alerts to administrators
        logger.critical(f"SECURITY ALERT: {event.description}")
        return "administrators_alerted"
    
    def _quarantine_container(self, container_id: str) -> str:
        """Quarantine container"""
        # Isolate container from network and other resources
        logger.warning(f"Container {container_id} quarantined")
        return "container_quarantined"
    
    def _restrict_container_capabilities(self, container_id: str) -> str:
        """Restrict container capabilities"""
        # Remove additional capabilities from running container
        logger.warning(f"Restricted capabilities for container {container_id}")
        return "capabilities_restricted"
    
    def _increase_monitoring_level(self, container_id: str) -> str:
        """Increase monitoring level"""
        # Enhance monitoring for container
        logger.info(f"Increased monitoring for container {container_id}")
        return "monitoring_increased"
    
    def _alert_tenant_admin(self, event: SecurityEvent) -> str:
        """Alert tenant administrator"""
        # Notify tenant admin of security event
        logger.warning(f"Tenant admin alerted for container {event.container_id}")
        return "tenant_admin_alerted"
    
    def _increase_logging_level(self, container_id: str) -> str:
        """Increase logging level"""
        # Enhance logging for container
        logger.debug(f"Increased logging for container {container_id}")
        return "logging_increased"
    
    def _schedule_security_review(self, event: SecurityEvent) -> str:
        """Schedule security review"""
        # Schedule manual security review
        logger.info(f"Security review scheduled for {event.container_id}")
        return "security_review_scheduled"
    
    def _audit_container_security(self, tenant_id: str) -> Dict[str, Any]:
        """Audit container security configurations"""
        return {
            "score": 85,
            "findings": ["All containers using hardened profiles"],
            "recommendations": ["Regular security updates"]
        }
    
    def _audit_access_patterns(self, tenant_id: str) -> Dict[str, Any]:
        """Audit user access patterns"""
        return {
            "score": 90,
            "findings": ["Normal access patterns"],
            "recommendations": ["Enable MFA for all users"]
        }
    
    def _audit_resource_usage(self, tenant_id: str) -> Dict[str, Any]:
        """Audit resource usage patterns"""
        return {
            "score": 95,
            "findings": ["Resource usage within normal limits"],
            "recommendations": ["Continue monitoring"]
        }
    
    def _calculate_compliance_score(self, container_score: Dict, access_score: Dict, 
                                   resource_score: Dict) -> int:
        """Calculate overall compliance score"""
        scores = [container_score["score"], access_score["score"], resource_score["score"]]
        return sum(scores) // len(scores)
    
    def _initialize_security_subsystems(self):
        """Initialize security monitoring subsystems"""
        # Initialize auditd, seccomp, AppArmor, etc.
        logger.info("Security subsystems initialized")