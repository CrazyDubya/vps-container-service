# VPS Secure Compute Manager - Production Docker Image
FROM ubuntu:22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Set locale
RUN apt-get update && apt-get install -y locales && \
    locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    pkg-config \
    libffi-dev \
    libssl-dev \
    curl \
    wget \
    unzip \
    iptables \
    bridge-utils \
    lvm2 \
    thin-provisioning-tools \
    cryptsetup \
    qemu-utils \
    socat \
    jq \
    lxc \
    lxc-templates \
    debootstrap \
    openvswitch-switch \
    apparmor-utils \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Firecracker
RUN wget -O /tmp/firecracker.tgz \
    https://github.com/firecracker-microvm/firecracker/releases/download/v1.4.0/firecracker-v1.4.0-x86_64.tgz && \
    tar -xzf /tmp/firecracker.tgz -C /tmp && \
    cp /tmp/release-v1.4.0-x86_64/firecracker-v1.4.0-x86_64 /usr/bin/firecracker && \
    cp /tmp/release-v1.4.0-x86_64/jailer-v1.4.0-x86_64 /usr/bin/jailer && \
    chmod +x /usr/bin/firecracker /usr/bin/jailer && \
    rm -rf /tmp/*

# Create application user
RUN useradd -r -m -s /bin/bash -d /app vps-secure && \
    mkdir -p /opt/vps-secure-compute/{templates,storage,backups,kernels,rootfs} && \
    mkdir -p /var/lib/vps-secure-compute/{volumes,snapshots,networks} && \
    mkdir -p /var/log/vps-secure-compute && \
    mkdir -p /etc/vps-secure-compute

# Set working directory
WORKDIR /app

# Copy application code
COPY . /app/

# Install Python dependencies
RUN pip3 install --no-cache-dir -e .[web,firecracker,lxc,monitoring]

# Download kernel for Firecracker
RUN wget -O /opt/vps-secure-compute/kernels/vmlinux.bin \
    https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/kernels/vmlinux.bin

# Download basic rootfs images
RUN wget -O /opt/vps-secure-compute/rootfs/ubuntu-22.04.ext4 \
    https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/rootfs/bionic.rootfs.ext4

# Create Alpine rootfs
RUN truncate -s 1G /opt/vps-secure-compute/rootfs/alpine-3.18.ext4 && \
    mkfs.ext4 /opt/vps-secure-compute/rootfs/alpine-3.18.ext4

# Set permissions
RUN chown -R vps-secure:vps-secure /opt/vps-secure-compute && \
    chown -R vps-secure:vps-secure /var/lib/vps-secure-compute && \
    chown -R vps-secure:vps-secure /var/log/vps-secure-compute && \
    chown -R vps-secure:vps-secure /app

# Create default configuration
RUN cat > /etc/vps-secure-compute/config.yaml << 'EOF'
database:
  url: "postgresql://vps_user:vps_pass@postgres:5432/vps_secure_compute"

jwt:
  secret_key: "docker-dev-secret-change-in-production"
  algorithm: "HS256"
  expire_minutes: 60

storage:
  path: "/opt/vps-secure-compute/storage"
  backup_path: "/opt/vps-secure-compute/backups"
  encryption_enabled: true

templates:
  path: "/opt/vps-secure-compute/templates"
  rootfs_path: "/opt/vps-secure-compute/rootfs"
  registry_url: "https://templates.vps-secure.com"

firecracker:
  binary: "/usr/bin/firecracker"
  jailer_binary: "/usr/bin/jailer"
  kernel_path: "/opt/vps-secure-compute/kernels"
  rootfs_path: "/opt/vps-secure-compute/rootfs"
  runtime_path: "/var/run/vps-secure-compute"

lxc:
  path: "/var/lib/lxc"
  template_path: "/usr/share/lxc/templates"

security:
  max_containers_per_user: 50
  max_memory_per_user_gb: 64
  max_cpu_per_user: 32
  audit_log_retention_days: 365

web:
  host: "0.0.0.0"
  port: 8080
  workers: 1
EOF

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Environment variables
ENV VPS_CONFIG_PATH=/etc/vps-secure-compute/config.yaml
ENV PYTHONPATH=/app

# Switch to application user
USER vps-secure

# Start command
CMD ["python3", "-m", "vps_secure_compute_manager.server"]