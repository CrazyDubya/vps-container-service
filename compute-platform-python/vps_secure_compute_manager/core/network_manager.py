"""
Network Management System for VPS Secure Compute Manager
Handles virtual networking, service discovery, load balancing, and network security
"""

import asyncio
import logging
import json
import ipaddress
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
import uuid
import subprocess

logger = logging.getLogger(__name__)

class NetworkType(Enum):
    BRIDGE = "bridge"
    OVERLAY = "overlay"
    MACVLAN = "macvlan"
    ISOLATED = "isolated"

class LoadBalancerType(Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    IP_HASH = "ip_hash"
    WEIGHTED = "weighted"

@dataclass
class NetworkConfig:
    """Network configuration"""
    name: str
    type: NetworkType
    subnet: str
    gateway: str
    tenant_id: str
    vlan_id: Optional[int] = None
    dns_servers: List[str] = None
    isolated: bool = True
    internet_access: bool = False
    created_at: datetime = None

@dataclass
class ServiceEndpoint:
    """Service endpoint for load balancing"""
    container_id: str
    ip_address: str
    port: int
    weight: int = 1
    healthy: bool = True
    last_health_check: Optional[datetime] = None

@dataclass
class LoadBalancer:
    """Load balancer configuration"""
    name: str
    frontend_port: int
    backend_endpoints: List[ServiceEndpoint]
    type: LoadBalancerType = LoadBalancerType.ROUND_ROBIN
    health_check_path: str = "/health"
    health_check_interval: int = 30
    tenant_id: str = None
    created_at: datetime = None

@dataclass
class NetworkPolicy:
    """Network security policy"""
    name: str
    tenant_id: str
    source_networks: List[str]
    destination_networks: List[str]
    allowed_ports: List[int]
    protocols: List[str]  # ["tcp", "udp", "icmp"]
    action: str = "allow"  # "allow", "deny"
    priority: int = 100
    created_at: datetime = None

class NetworkManager:
    """Commercial-grade network management system"""
    
    def __init__(self):
        self.networks: Dict[str, NetworkConfig] = {}
        self.load_balancers: Dict[str, LoadBalancer] = {}
        self.network_policies: Dict[str, NetworkPolicy] = {}
        self.container_networks: Dict[str, List[str]] = {}  # container_id -> network_names
        self.ip_allocations: Dict[str, Dict[str, str]] = {}  # network_name -> {container_id: ip}
        
        # Initialize default networks
        asyncio.create_task(self._initialize_default_networks())
    
    async def _initialize_default_networks(self):
        """Initialize default networks"""
        # Default bridge network
        await self.create_network(
            name="default",
            network_type=NetworkType.BRIDGE,
            subnet="172.17.0.0/16",
            gateway="172.17.0.1",
            tenant_id="system",
            internet_access=True
        )
        
        # Isolated tenant networks will be created on-demand
    
    async def create_network(self, 
                           name: str,
                           network_type: NetworkType,
                           subnet: str,
                           gateway: str,
                           tenant_id: str,
                           vlan_id: Optional[int] = None,
                           dns_servers: List[str] = None,
                           isolated: bool = True,
                           internet_access: bool = False) -> bool:
        """Create a virtual network"""
        try:
            # Validate subnet
            network = ipaddress.IPv4Network(subnet, strict=False)
            gateway_ip = ipaddress.IPv4Address(gateway)
            
            if gateway_ip not in network:
                raise ValueError(f"Gateway {gateway} not in subnet {subnet}")
            
            # Check if network already exists
            if name in self.networks:
                raise ValueError(f"Network {name} already exists")
            
            network_config = NetworkConfig(
                name=name,
                type=network_type,
                subnet=subnet,
                gateway=gateway,
                tenant_id=tenant_id,
                vlan_id=vlan_id,
                dns_servers=dns_servers or ["8.8.8.8", "8.8.4.4"],
                isolated=isolated,
                internet_access=internet_access,
                created_at=datetime.now(timezone.utc)
            )
            
            # Create network infrastructure
            if network_type == NetworkType.BRIDGE:
                await self._create_bridge_network(network_config)
            elif network_type == NetworkType.OVERLAY:
                await self._create_overlay_network(network_config)
            elif network_type == NetworkType.MACVLAN:
                await self._create_macvlan_network(network_config)
            elif network_type == NetworkType.ISOLATED:
                await self._create_isolated_network(network_config)
            
            # Store network configuration
            self.networks[name] = network_config
            self.ip_allocations[name] = {}
            
            logger.info(f"Created network {name} for tenant {tenant_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create network {name}: {e}")
            return False
    
    async def _create_bridge_network(self, config: NetworkConfig):
        """Create bridge network using Linux bridges"""
        bridge_name = f"vps-{config.name}"
        
        # Create bridge
        await self._run_command([
            "ip", "link", "add", "name", bridge_name, "type", "bridge"
        ])
        
        # Configure bridge IP
        await self._run_command([
            "ip", "addr", "add", f"{config.gateway}/{config.subnet.split('/')[1]}", "dev", bridge_name
        ])
        
        # Bring bridge up
        await self._run_command([
            "ip", "link", "set", "dev", bridge_name, "up"
        ])
        
        # Configure NAT for internet access
        if config.internet_access:
            await self._configure_nat(config.subnet, bridge_name)
        
        # Configure network isolation
        if config.isolated:
            await self._configure_isolation(bridge_name, config.tenant_id)
    
    async def _create_overlay_network(self, config: NetworkConfig):
        """Create overlay network using VXLAN"""
        if not config.vlan_id:
            config.vlan_id = hash(config.name) % 16777215  # 24-bit VXLAN ID
        
        vxlan_name = f"vxlan-{config.name}"
        bridge_name = f"br-{config.name}"
        
        # Create VXLAN interface
        await self._run_command([
            "ip", "link", "add", vxlan_name, "type", "vxlan",
            "id", str(config.vlan_id),
            "local", "127.0.0.1",  # This would be the node's IP in a multi-node setup
            "dstport", "4789"
        ])
        
        # Create bridge and add VXLAN
        await self._run_command([
            "ip", "link", "add", "name", bridge_name, "type", "bridge"
        ])
        
        await self._run_command([
            "ip", "link", "set", vxlan_name, "master", bridge_name
        ])
        
        # Configure bridge
        await self._run_command([
            "ip", "addr", "add", f"{config.gateway}/{config.subnet.split('/')[1]}", "dev", bridge_name
        ])
        
        # Bring interfaces up
        await self._run_command(["ip", "link", "set", "dev", vxlan_name, "up"])
        await self._run_command(["ip", "link", "set", "dev", bridge_name, "up"])
    
    async def _create_macvlan_network(self, config: NetworkConfig):
        """Create MACVLAN network"""
        # This would create MACVLAN interfaces
        # Implementation depends on the host network configuration
        pass
    
    async def _create_isolated_network(self, config: NetworkConfig):
        """Create completely isolated network"""
        bridge_name = f"iso-{config.name}"
        
        # Create isolated bridge (no external connectivity)
        await self._run_command([
            "ip", "link", "add", "name", bridge_name, "type", "bridge"
        ])
        
        await self._run_command([
            "ip", "addr", "add", f"{config.gateway}/{config.subnet.split('/')[1]}", "dev", bridge_name
        ])
        
        await self._run_command([
            "ip", "link", "set", "dev", bridge_name, "up"
        ])
    
    async def _configure_nat(self, subnet: str, bridge_name: str):
        """Configure NAT for internet access"""
        # Add iptables rules for NAT
        await self._run_command([
            "iptables", "-t", "nat", "-A", "POSTROUTING",
            "-s", subnet, "-j", "MASQUERADE"
        ])
        
        await self._run_command([
            "iptables", "-A", "FORWARD",
            "-i", bridge_name, "-j", "ACCEPT"
        ])
        
        await self._run_command([
            "iptables", "-A", "FORWARD",
            "-o", bridge_name, "-j", "ACCEPT"
        ])
    
    async def _configure_isolation(self, bridge_name: str, tenant_id: str):
        """Configure network isolation between tenants"""
        # Add iptables rules to prevent cross-tenant communication
        # This is a simplified example - production would need more sophisticated rules
        
        # Block traffic between different tenant bridges
        for other_network in self.networks.values():
            if other_network.tenant_id != tenant_id:
                other_bridge = f"vps-{other_network.name}"
                await self._run_command([
                    "iptables", "-A", "FORWARD",
                    "-i", bridge_name, "-o", other_bridge, "-j", "DROP"
                ])
                await self._run_command([
                    "iptables", "-A", "FORWARD",
                    "-i", other_bridge, "-o", bridge_name, "-j", "DROP"
                ])
    
    async def attach_container_to_network(self, 
                                        container_id: str,
                                        network_name: str,
                                        ip_address: Optional[str] = None) -> Optional[str]:
        """Attach container to network and assign IP"""
        try:
            if network_name not in self.networks:
                raise ValueError(f"Network {network_name} does not exist")
            
            network_config = self.networks[network_name]
            
            # Allocate IP address
            if not ip_address:
                ip_address = await self._allocate_ip(network_name)
            
            if not ip_address:
                raise ValueError(f"No available IP addresses in network {network_name}")
            
            # Create veth pair
            veth_host = f"veth-{container_id[:12]}"
            veth_container = f"eth-{container_id[:12]}"
            
            await self._run_command([
                "ip", "link", "add", veth_host, "type", "veth", "peer", "name", veth_container
            ])
            
            # Attach host end to bridge
            bridge_name = f"vps-{network_name}" if network_config.type == NetworkType.BRIDGE else f"br-{network_name}"
            await self._run_command([
                "ip", "link", "set", veth_host, "master", bridge_name
            ])
            
            await self._run_command([
                "ip", "link", "set", "dev", veth_host, "up"
            ])
            
            # Move container end to container namespace (this would be done by the container backend)
            # For now, we'll just record the assignment
            
            # Record the assignment
            if container_id not in self.container_networks:
                self.container_networks[container_id] = []
            self.container_networks[container_id].append(network_name)
            self.ip_allocations[network_name][container_id] = ip_address
            
            logger.info(f"Attached container {container_id} to network {network_name} with IP {ip_address}")
            return ip_address
            
        except Exception as e:
            logger.error(f"Failed to attach container {container_id} to network {network_name}: {e}")
            return None
    
    async def _allocate_ip(self, network_name: str) -> Optional[str]:
        """Allocate available IP address in network"""
        network_config = self.networks[network_name]
        subnet = ipaddress.IPv4Network(network_config.subnet, strict=False)
        allocated_ips = set(self.ip_allocations[network_name].values())
        
        # Reserve gateway and network/broadcast addresses
        reserved_ips = {str(subnet.network_address), str(subnet.broadcast_address), network_config.gateway}
        
        for ip in subnet.hosts():
            ip_str = str(ip)
            if ip_str not in allocated_ips and ip_str not in reserved_ips:
                return ip_str
        
        return None
    
    async def detach_container_from_network(self, container_id: str, network_name: str) -> bool:
        """Detach container from network"""
        try:
            if network_name not in self.networks:
                return False
            
            # Remove veth interface
            veth_host = f"veth-{container_id[:12]}"
            await self._run_command(["ip", "link", "delete", veth_host], ignore_errors=True)
            
            # Update records
            if container_id in self.container_networks:
                if network_name in self.container_networks[container_id]:
                    self.container_networks[container_id].remove(network_name)
            
            if network_name in self.ip_allocations and container_id in self.ip_allocations[network_name]:
                del self.ip_allocations[network_name][container_id]
            
            logger.info(f"Detached container {container_id} from network {network_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to detach container {container_id} from network {network_name}: {e}")
            return False
    
    async def create_load_balancer(self,
                                 name: str,
                                 frontend_port: int,
                                 backend_containers: List[str],
                                 backend_port: int,
                                 tenant_id: str,
                                 lb_type: LoadBalancerType = LoadBalancerType.ROUND_ROBIN) -> bool:
        """Create load balancer for service"""
        try:
            # Get container IPs
            endpoints = []
            for container_id in backend_containers:
                container_networks = self.container_networks.get(container_id, [])
                if container_networks:
                    # Use first network's IP
                    network_name = container_networks[0]
                    ip = self.ip_allocations[network_name].get(container_id)
                    if ip:
                        endpoints.append(ServiceEndpoint(
                            container_id=container_id,
                            ip_address=ip,
                            port=backend_port
                        ))
            
            if not endpoints:
                raise ValueError("No valid backend endpoints found")
            
            load_balancer = LoadBalancer(
                name=name,
                frontend_port=frontend_port,
                backend_endpoints=endpoints,
                type=lb_type,
                tenant_id=tenant_id,
                created_at=datetime.now(timezone.utc)
            )
            
            # Configure load balancer (using iptables DNAT rules)
            await self._configure_load_balancer(load_balancer)
            
            self.load_balancers[name] = load_balancer
            
            logger.info(f"Created load balancer {name} for tenant {tenant_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create load balancer {name}: {e}")
            return False
    
    async def _configure_load_balancer(self, lb: LoadBalancer):
        """Configure load balancer using iptables"""
        # This is a simplified implementation
        # Production would use HAProxy, nginx, or similar
        
        for i, endpoint in enumerate(lb.backend_endpoints):
            # Create DNAT rule for each backend
            await self._run_command([
                "iptables", "-t", "nat", "-A", "PREROUTING",
                "-p", "tcp", "--dport", str(lb.frontend_port),
                "-m", "statistic", "--mode", "nth", "--every", str(len(lb.backend_endpoints)), "--packet", str(i),
                "-j", "DNAT", "--to-destination", f"{endpoint.ip_address}:{endpoint.port}"
            ])
    
    async def add_network_policy(self, policy: NetworkPolicy) -> bool:
        """Add network security policy"""
        try:
            self.network_policies[policy.name] = policy
            
            # Apply policy using iptables
            await self._apply_network_policy(policy)
            
            logger.info(f"Added network policy {policy.name} for tenant {policy.tenant_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add network policy {policy.name}: {e}")
            return False
    
    async def _apply_network_policy(self, policy: NetworkPolicy):
        """Apply network policy using iptables"""
        for src_network in policy.source_networks:
            for dst_network in policy.destination_networks:
                for port in policy.allowed_ports:
                    for protocol in policy.protocols:
                        action = "ACCEPT" if policy.action == "allow" else "DROP"
                        
                        await self._run_command([
                            "iptables", "-A", "FORWARD",
                            "-s", src_network, "-d", dst_network,
                            "-p", protocol, "--dport", str(port),
                            "-j", action
                        ])
    
    def get_container_networks(self, container_id: str) -> List[Dict[str, Any]]:
        """Get networks attached to container"""
        networks = []
        container_networks = self.container_networks.get(container_id, [])
        
        for network_name in container_networks:
            if network_name in self.networks:
                network_config = self.networks[network_name]
                ip_address = self.ip_allocations[network_name].get(container_id)
                
                networks.append({
                    "name": network_name,
                    "type": network_config.type.value,
                    "ip_address": ip_address,
                    "subnet": network_config.subnet,
                    "gateway": network_config.gateway
                })
        
        return networks
    
    def list_networks(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List networks, optionally filtered by tenant"""
        networks = []
        
        for network_config in self.networks.values():
            if tenant_id and network_config.tenant_id != tenant_id:
                continue
            
            networks.append({
                "name": network_config.name,
                "type": network_config.type.value,
                "subnet": network_config.subnet,
                "gateway": network_config.gateway,
                "tenant_id": network_config.tenant_id,
                "isolated": network_config.isolated,
                "internet_access": network_config.internet_access,
                "connected_containers": len(self.ip_allocations.get(network_config.name, {})),
                "created_at": network_config.created_at.isoformat() if network_config.created_at else None
            })
        
        return networks
    
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
    
    async def cleanup_container_networking(self, container_id: str):
        """Clean up all networking for a container"""
        networks_to_detach = self.container_networks.get(container_id, []).copy()
        
        for network_name in networks_to_detach:
            await self.detach_container_from_network(container_id, network_name)
        
        if container_id in self.container_networks:
            del self.container_networks[container_id]
    
    async def delete_network(self, network_name: str) -> bool:
        """Delete a network"""
        try:
            if network_name not in self.networks:
                return False
            
            network_config = self.networks[network_name]
            
            # Detach all containers
            containers_to_detach = list(self.ip_allocations.get(network_name, {}).keys())
            for container_id in containers_to_detach:
                await self.detach_container_from_network(container_id, network_name)
            
            # Remove network infrastructure
            bridge_name = f"vps-{network_name}" if network_config.type == NetworkType.BRIDGE else f"br-{network_name}"
            await self._run_command(["ip", "link", "delete", bridge_name], ignore_errors=True)
            
            # Clean up records
            del self.networks[network_name]
            if network_name in self.ip_allocations:
                del self.ip_allocations[network_name]
            
            logger.info(f"Deleted network {network_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete network {network_name}: {e}")
            return False