#!/bin/bash
set -e

# VPS Secure Compute Manager - Production Infrastructure Setup
# This script sets up real Firecracker, LXC, networking, and storage infrastructure

echo "🔧 Setting up VPS Secure Compute Manager Production Infrastructure..."

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run as root" 
   exit 1
fi

# System requirements check
echo "📋 Checking system requirements..."

# Check CPU virtualization
if ! grep -E '(vmx|svm)' /proc/cpuinfo > /dev/null; then
    echo "❌ CPU virtualization (VT-x/AMD-V) not available"
    exit 1
fi

# Check KVM support
if ! lsmod | grep kvm > /dev/null; then
    echo "⚠️  KVM module not loaded, attempting to load..."
    modprobe kvm
    modprobe kvm_intel || modprobe kvm_amd
fi

echo "✅ System requirements met"

# Update system
echo "📦 Updating system packages..."
apt-get update
apt-get upgrade -y

# Install required packages
echo "📦 Installing required packages..."
apt-get install -y \
    curl wget unzip \
    iptables bridge-utils \
    lvm2 thin-provisioning-tools \
    cryptsetup \
    qemu-utils \
    socat \
    jq \
    python3-dev \
    build-essential \
    pkg-config \
    libffi-dev \
    libssl-dev

# Install Firecracker
echo "🔥 Installing Firecracker..."
FIRECRACKER_VERSION="v1.4.0"
FIRECRACKER_URL="https://github.com/firecracker-microvm/firecracker/releases/download/${FIRECRACKER_VERSION}/firecracker-${FIRECRACKER_VERSION}-x86_64.tgz"

cd /tmp
wget -O firecracker.tgz "${FIRECRACKER_URL}"
tar -xzf firecracker.tgz

# Install binaries
cp release-${FIRECRACKER_VERSION}-x86_64/firecracker-${FIRECRACKER_VERSION}-x86_64 /usr/bin/firecracker
cp release-${FIRECRACKER_VERSION}-x86_64/jailer-${FIRECRACKER_VERSION}-x86_64 /usr/bin/jailer
chmod +x /usr/bin/firecracker /usr/bin/jailer

echo "✅ Firecracker installed successfully"

# Install LXC
echo "📦 Installing LXC..."
apt-get install -y lxc lxc-templates debootstrap

# Configure LXC
echo "🔧 Configuring LXC..."
cat > /etc/lxc/default.conf << 'EOF'
lxc.net.0.type = veth
lxc.net.0.link = lxcbr0
lxc.net.0.flags = up
lxc.net.0.hwaddr = 00:16:3e:xx:xx:xx
lxc.apparmor.profile = generated
lxc.apparmor.allow_nesting = 1
EOF

systemctl enable lxc-net
systemctl start lxc-net

echo "✅ LXC installed and configured"

# Set up storage infrastructure
echo "💾 Setting up storage infrastructure..."

# Create storage directories
mkdir -p /opt/vps-secure-compute/{storage,templates,backups,kernels}
mkdir -p /var/lib/vps-secure-compute/{volumes,snapshots}
mkdir -p /var/log/vps-secure-compute

# Set up LVM thin provisioning for efficient storage
if ! vgs vps-storage > /dev/null 2>&1; then
    echo "⚠️  LVM volume group 'vps-storage' not found"
    echo "📋 Available block devices:"
    lsblk
    echo ""
    echo "Please create LVM storage manually:"
    echo "  pvcreate /dev/sdX  # Replace X with your storage device"
    echo "  vgcreate vps-storage /dev/sdX"
    echo "  lvcreate -L 100G -T vps-storage/thin-pool"
    echo ""
    echo "For testing, creating file-based storage..."
    
    # Create file-based storage for testing
    mkdir -p /opt/vps-storage
    truncate -s 50G /opt/vps-storage/storage.img
    LOOP_DEVICE=$(losetup -f --show /opt/vps-storage/storage.img)
    pvcreate "$LOOP_DEVICE"
    vgcreate vps-storage "$LOOP_DEVICE"
    lvcreate -L 40G -T vps-storage/thin-pool
    echo "✅ File-based storage created for testing"
else
    echo "✅ LVM volume group 'vps-storage' found"
fi

# Set up networking infrastructure
echo "🌐 Setting up networking infrastructure..."

# Install Open vSwitch for advanced networking
apt-get install -y openvswitch-switch

# Enable and start OVS
systemctl enable openvswitch-switch
systemctl start openvswitch-switch

# Create default bridge
ovs-vsctl --may-exist add-br vps-br0

# Configure iptables for container networking
cat > /etc/iptables/rules.v4 << 'EOF'
*nat
:PREROUTING ACCEPT [0:0]
:INPUT ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
:POSTROUTING ACCEPT [0:0]
# Allow container internet access
-A POSTROUTING -s 172.16.0.0/12 -j MASQUERADE
COMMIT

*filter
:INPUT ACCEPT [0:0]
:FORWARD ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
# Allow container forwarding
-A FORWARD -i vps-+ -j ACCEPT
-A FORWARD -o vps-+ -j ACCEPT
# Allow established connections
-A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT
COMMIT
EOF

# Install iptables-persistent to save rules
DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent

echo "✅ Networking infrastructure configured"

# Download and prepare base templates
echo "📦 Setting up base container templates..."

# Download minimal kernel for Firecracker
KERNEL_URL="https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/kernels/vmlinux.bin"
wget -O /opt/vps-secure-compute/kernels/vmlinux.bin "$KERNEL_URL"

# Create template download script
cat > /opt/vps-secure-compute/download-templates.sh << 'EOF'
#!/bin/bash
set -e

TEMPLATES_DIR="/opt/vps-secure-compute/templates"
ROOTFS_DIR="/opt/vps-secure-compute/rootfs"

mkdir -p "$ROOTFS_DIR"

echo "📦 Downloading base templates..."

# Download Ubuntu 22.04 rootfs for Firecracker
if [ ! -f "$ROOTFS_DIR/ubuntu-22.04.ext4" ]; then
    echo "⬇️  Downloading Ubuntu 22.04 rootfs..."
    wget -O "$ROOTFS_DIR/ubuntu-22.04.ext4" \
        "https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/rootfs/bionic.rootfs.ext4"
fi

# Download Alpine rootfs for lightweight containers
if [ ! -f "$ROOTFS_DIR/alpine-3.18.ext4" ]; then
    echo "⬇️  Creating Alpine 3.18 rootfs..."
    truncate -s 1G "$ROOTFS_DIR/alpine-3.18.ext4"
    mkfs.ext4 "$ROOTFS_DIR/alpine-3.18.ext4"
    
    mkdir -p /tmp/alpine-mount
    mount -o loop "$ROOTFS_DIR/alpine-3.18.ext4" /tmp/alpine-mount
    
    # Download and extract Alpine minirootfs
    wget -O /tmp/alpine-minirootfs.tar.gz \
        "https://dl-cdn.alpinelinux.org/alpine/v3.18/releases/x86_64/alpine-minirootfs-3.18.4-x86_64.tar.gz"
    tar -xzf /tmp/alpine-minirootfs.tar.gz -C /tmp/alpine-mount
    
    umount /tmp/alpine-mount
    rmdir /tmp/alpine-mount
    rm /tmp/alpine-minirootfs.tar.gz
fi

# Create Python development template
if [ ! -f "$ROOTFS_DIR/python-3.11.ext4" ]; then
    echo "⬇️  Creating Python 3.11 development template..."
    cp "$ROOTFS_DIR/ubuntu-22.04.ext4" "$ROOTFS_DIR/python-3.11.ext4"
    
    # Resize to 2GB for development tools
    resize2fs "$ROOTFS_DIR/python-3.11.ext4" 2G
fi

echo "✅ Base templates ready"
EOF

chmod +x /opt/vps-secure-compute/download-templates.sh

# Set up systemd service
echo "🔧 Setting up systemd service..."
cat > /etc/systemd/system/vps-secure-compute.service << 'EOF'
[Unit]
Description=VPS Secure Compute Manager
After=network.target openvswitch-switch.service lxc-net.service
Requires=openvswitch-switch.service

[Service]
Type=forking
User=root
Group=root
WorkingDirectory=/opt/vps-secure-compute-manager
ExecStart=/usr/bin/python3 -m vps_secure_compute_manager.server
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process
Restart=on-failure
RestartSec=30

# Security settings
NoNewPrivileges=false
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/vps-secure-compute /var/lib/vps-secure-compute /var/log/vps-secure-compute

[Install]
WantedBy=multi-user.target
EOF

# Set up logging
echo "📝 Setting up logging..."
cat > /etc/rsyslog.d/50-vps-secure-compute.conf << 'EOF'
# VPS Secure Compute Manager logging
:programname, isequal, "vps-secure-compute" /var/log/vps-secure-compute/main.log
& stop
EOF

systemctl restart rsyslog

# Set up log rotation
cat > /etc/logrotate.d/vps-secure-compute << 'EOF'
/var/log/vps-secure-compute/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    sharedscripts
    postrotate
        systemctl reload vps-secure-compute
    endscript
}
EOF

# Create user and group
echo "👤 Setting up service user..."
if ! getent group vps-secure-compute > /dev/null; then
    groupadd vps-secure-compute
fi

if ! getent passwd vps-secure-compute > /dev/null; then
    useradd -r -g vps-secure-compute -d /opt/vps-secure-compute -s /bin/false vps-secure-compute
fi

# Set permissions
chown -R vps-secure-compute:vps-secure-compute /opt/vps-secure-compute
chown -R vps-secure-compute:vps-secure-compute /var/lib/vps-secure-compute
chown -R vps-secure-compute:vps-secure-compute /var/log/vps-secure-compute

# Add vps-secure-compute user to required groups
usermod -a -G kvm,lxd,docker vps-secure-compute

# Enable IP forwarding
echo "🌐 Enabling IP forwarding..."
echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
echo 'net.ipv6.conf.all.forwarding=1' >> /etc/sysctl.conf
sysctl -p

# Configure security
echo "🔒 Configuring security..."

# AppArmor profiles for containers
apt-get install -y apparmor-utils

# Create AppArmor profile for Firecracker
cat > /etc/apparmor.d/firecracker << 'EOF'
#include <tunables/global>

/usr/bin/firecracker {
  #include <abstractions/base>
  
  capability net_admin,
  capability sys_admin,
  capability dac_override,
  
  /usr/bin/firecracker mr,
  /dev/kvm rw,
  /dev/net/tun rw,
  /sys/fs/cgroup/** rw,
  
  /opt/vps-secure-compute/** rw,
  /var/lib/vps-secure-compute/** rw,
  
  owner /tmp/** rw,
  
  # Network access
  network inet dgram,
  network inet stream,
  network unix dgram,
  network unix stream,
}
EOF

# Load AppArmor profile
apparmor_parser -r /etc/apparmor.d/firecracker

# Set up monitoring
echo "📊 Setting up monitoring..."
apt-get install -y prometheus-node-exporter

# Create firewall rules for monitoring
ufw allow 9100/tcp comment "Prometheus Node Exporter"

# Download templates
echo "📦 Downloading container templates..."
/opt/vps-secure-compute/download-templates.sh

# Verify installation
echo "🔍 Verifying installation..."

# Check Firecracker
if firecracker --version > /dev/null 2>&1; then
    echo "✅ Firecracker: $(firecracker --version)"
else
    echo "❌ Firecracker installation failed"
    exit 1
fi

# Check LXC
if lxc-info --version > /dev/null 2>&1; then
    echo "✅ LXC: $(lxc-info --version)"
else
    echo "❌ LXC installation failed"
    exit 1
fi

# Check OVS
if ovs-vsctl --version > /dev/null 2>&1; then
    echo "✅ Open vSwitch: $(ovs-vsctl --version | head -n1)"
else
    echo "❌ Open vSwitch installation failed"
    exit 1
fi

# Check storage
if vgs vps-storage > /dev/null 2>&1; then
    echo "✅ LVM Storage: $(vgs vps-storage --noheadings -o vg_size)"
else
    echo "❌ LVM storage not available"
fi

echo ""
echo "🎉 Production infrastructure setup complete!"
echo ""
echo "📋 Next steps:"
echo "  1. Install VPS Secure Compute Manager Python package"
echo "  2. Configure /etc/vps-secure-compute/config.yaml"
echo "  3. Initialize database: vps-secure-admin init-db"
echo "  4. Start service: systemctl enable vps-secure-compute"
echo "  5. Start service: systemctl start vps-secure-compute"
echo ""
echo "📊 Status check:"
echo "  systemctl status vps-secure-compute"
echo "  journalctl -u vps-secure-compute -f"
echo ""
echo "🔧 Firecracker test:"
echo "  vps-secure create-container --template ubuntu-22.04 --name test-vm"
echo ""