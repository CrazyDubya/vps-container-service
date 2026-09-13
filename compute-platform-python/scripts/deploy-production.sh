#!/bin/bash
set -e

# VPS Secure Compute Manager - Production Deployment Script
# This script deploys a complete production-ready installation

echo "🚀 Deploying VPS Secure Compute Manager to Production..."

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run as root" 
   exit 1
fi

# Configuration
VPS_USER="vps-secure-compute"
VPS_HOME="/opt/vps-secure-compute-manager"
VPS_CONFIG="/etc/vps-secure-compute"
VPS_DATA="/var/lib/vps-secure-compute"
VPS_LOGS="/var/log/vps-secure-compute"

echo "📋 Configuration:"
echo "  User: $VPS_USER"
echo "  Home: $VPS_HOME"
echo "  Config: $VPS_CONFIG"
echo "  Data: $VPS_DATA"
echo "  Logs: $VPS_LOGS"
echo ""

# Step 1: Run infrastructure setup
echo "🔧 Step 1: Setting up infrastructure..."
if [ -f "./setup-production-infrastructure.sh" ]; then
    ./setup-production-infrastructure.sh
else
    echo "❌ Infrastructure setup script not found"
    echo "Please run from the scripts directory"
    exit 1
fi

# Step 2: Install Python package
echo "📦 Step 2: Installing VPS Secure Compute Manager..."

# Install in development mode for now (production would install from PyPI)
cd "$(dirname "$0")/.."
pip install -e .[dev,firecracker,lxc,web]

# Step 3: Create directory structure
echo "📁 Step 3: Creating directory structure..."
mkdir -p "$VPS_CONFIG"
mkdir -p "$VPS_DATA"/{volumes,snapshots,networks}
mkdir -p "$VPS_LOGS"
mkdir -p /opt/vps-secure-compute/{templates,storage,backups,kernels,rootfs}

# Step 4: Create production configuration
echo "⚙️  Step 4: Creating production configuration..."
cat > "$VPS_CONFIG/config.yaml" << 'EOF'
# VPS Secure Compute Manager - Production Configuration

database:
  url: "postgresql://vps_user:vps_secure_password@localhost:5432/vps_secure_compute"
  pool_size: 20
  max_overflow: 30
  pool_timeout: 30
  pool_recycle: 3600

jwt:
  secret_key: "CHANGE_THIS_TO_RANDOM_SECRET"
  algorithm: "HS256"
  expire_minutes: 60

storage:
  path: "/opt/vps-secure-compute/storage"
  backup_path: "/opt/vps-secure-compute/backups"
  encryption_enabled: true
  backup_retention_days: 30

templates:
  path: "/opt/vps-secure-compute/templates"
  rootfs_path: "/opt/vps-secure-compute/rootfs"
  registry_url: "https://templates.vps-secure.com"
  auto_update: true
  update_interval_hours: 24

firecracker:
  binary: "/usr/bin/firecracker"
  jailer_binary: "/usr/bin/jailer"
  kernel_path: "/opt/vps-secure-compute/kernels"
  rootfs_path: "/opt/vps-secure-compute/rootfs"
  runtime_path: "/var/run/vps-secure-compute"
  default_kernel: "vmlinux.bin"

lxc:
  path: "/var/lib/lxc"
  template_path: "/usr/share/lxc/templates"
  config_path: "/var/lib/lxc"

networking:
  default_bridge: "vps-br0"
  ip_range: "172.16.0.0/12"
  enable_ipv6: false
  dns_servers: ["8.8.8.8", "8.8.4.4"]

security:
  max_containers_per_user: 50
  max_memory_per_user_gb: 64
  max_cpu_per_user: 32
  max_storage_per_user_gb: 500
  audit_log_retention_days: 365
  session_timeout_minutes: 60
  rate_limit_requests_per_minute: 100
  enable_2fa: false

monitoring:
  enable_metrics: true
  metrics_port: 9090
  enable_logging: true
  log_level: "INFO"
  enable_audit: true

web:
  host: "0.0.0.0"
  port: 8080
  workers: 4
  enable_ssl: true
  ssl_cert_path: "/etc/ssl/certs/vps-secure.crt"
  ssl_key_path: "/etc/ssl/private/vps-secure.key"

backup:
  enabled: true
  schedule: "0 2 * * *"  # Daily at 2 AM
  retention_days: 30
  compression: true
  encryption: true
EOF

# Step 5: Generate JWT secret
echo "🔐 Step 5: Generating JWT secret..."
JWT_SECRET=$(openssl rand -hex 32)
sed -i "s/CHANGE_THIS_TO_RANDOM_SECRET/$JWT_SECRET/" "$VPS_CONFIG/config.yaml"

# Step 6: Set up PostgreSQL database
echo "🗄️  Step 6: Setting up PostgreSQL database..."
apt-get install -y postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql << EOF
CREATE USER vps_user WITH PASSWORD 'vps_secure_password';
CREATE DATABASE vps_secure_compute OWNER vps_user;
GRANT ALL PRIVILEGES ON DATABASE vps_secure_compute TO vps_user;
EOF

# Step 7: Initialize database
echo "🔧 Step 7: Initializing database..."
export VPS_CONFIG_PATH="$VPS_CONFIG/config.yaml"
python -c "
from vps_secure_compute_manager.core.database import DatabaseManager
import yaml

with open('$VPS_CONFIG/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

db = DatabaseManager(config['database']['url'])
db.create_tables()
db.initialize_default_data()
print('Database initialized successfully')
"

# Step 8: Create systemd service
echo "⚙️  Step 8: Creating systemd service..."
cat > /etc/systemd/system/vps-secure-compute.service << EOF
[Unit]
Description=VPS Secure Compute Manager
Documentation=https://docs.vps-secure.com
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=exec
User=root
Group=root
WorkingDirectory=$VPS_HOME
Environment=VPS_CONFIG_PATH=$VPS_CONFIG/config.yaml
Environment=PYTHONPATH=$VPS_HOME
ExecStart=/usr/local/bin/python -m vps_secure_compute_manager.server
ExecReload=/bin/kill -HUP \$MAINPID
KillMode=mixed
Restart=on-failure
RestartSec=10
TimeoutStopSec=30

# Security settings
NoNewPrivileges=false
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$VPS_DATA $VPS_LOGS /opt/vps-secure-compute /var/run/vps-secure-compute /tmp

# Resource limits
LimitNOFILE=65536
LimitNPROC=4096

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=vps-secure-compute

[Install]
WantedBy=multi-user.target
EOF

# Step 9: Create nginx configuration
echo "🌐 Step 9: Setting up nginx reverse proxy..."
apt-get install -y nginx

cat > /etc/nginx/sites-available/vps-secure-compute << 'EOF'
upstream vps_secure_compute {
    server 127.0.0.1:8080;
}

server {
    listen 80;
    server_name your-domain.com www.your-domain.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com www.your-domain.com;
    
    # SSL configuration (replace with your certificates)
    ssl_certificate /etc/ssl/certs/vps-secure.crt;
    ssl_private_key /etc/ssl/private/vps-secure.key;
    
    # SSL security
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload";
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdnjs.cloudflare.com; font-src 'self' cdnjs.cloudflare.com; img-src 'self' data:;";
    
    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
    
    location / {
        proxy_pass http://vps_secure_compute;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    location /api/ {
        limit_req zone=api burst=20 nodelay;
        
        proxy_pass http://vps_secure_compute;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /login {
        limit_req zone=login burst=5 nodelay;
        
        proxy_pass http://vps_secure_compute;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # Static files (if served directly by nginx)
    location /static/ {
        alias /opt/vps-secure-compute-manager/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# Enable site
ln -sf /etc/nginx/sites-available/vps-secure-compute /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Step 10: Set up SSL certificates (self-signed for demo)
echo "🔒 Step 10: Setting up SSL certificates..."
mkdir -p /etc/ssl/private
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/ssl/private/vps-secure.key \
    -out /etc/ssl/certs/vps-secure.crt \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=your-domain.com"

chmod 600 /etc/ssl/private/vps-secure.key

# Step 11: Set up log rotation
echo "📝 Step 11: Setting up log rotation..."
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

# Step 12: Set up firewall
echo "🔥 Step 12: Setting up firewall..."
ufw --force enable
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 9090/tcp comment "Prometheus metrics"

# Step 13: Set permissions
echo "👤 Step 13: Setting permissions..."
chown -R $VPS_USER:$VPS_USER "$VPS_DATA" "$VPS_LOGS" /opt/vps-secure-compute
chmod 755 "$VPS_CONFIG"
chmod 600 "$VPS_CONFIG/config.yaml"

# Step 14: Enable and start services
echo "🚀 Step 14: Starting services..."
systemctl daemon-reload
systemctl enable vps-secure-compute
systemctl enable nginx
systemctl enable postgresql

# Test nginx configuration
nginx -t

systemctl restart postgresql
systemctl restart nginx
systemctl start vps-secure-compute

# Step 15: Wait for services to start
echo "⏳ Step 15: Waiting for services to start..."
sleep 10

# Step 16: Verify installation
echo "🔍 Step 16: Verifying installation..."

# Check service status
if systemctl is-active --quiet vps-secure-compute; then
    echo "✅ VPS Secure Compute Manager service is running"
else
    echo "❌ VPS Secure Compute Manager service failed to start"
    journalctl -u vps-secure-compute --no-pager -n 20
    exit 1
fi

if systemctl is-active --quiet nginx; then
    echo "✅ Nginx is running"
else
    echo "❌ Nginx failed to start"
    exit 1
fi

if systemctl is-active --quiet postgresql; then
    echo "✅ PostgreSQL is running"
else
    echo "❌ PostgreSQL failed to start"
    exit 1
fi

# Test HTTP connection
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health | grep -q "200"; then
    echo "✅ HTTP health check passed"
else
    echo "❌ HTTP health check failed"
fi

# Step 17: Create admin user
echo "👤 Step 17: Creating admin user..."
python -c "
import sys
sys.path.insert(0, '/opt/vps-secure-compute-manager')

from vps_secure_compute_manager.core.database import DatabaseManager
import yaml

with open('$VPS_CONFIG/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

db = DatabaseManager(config['database']['url'])

# Create system admin tenant and user
result = db.create_tenant_with_defaults(
    name='system-admin',
    display_name='System Administration',
    admin_email='admin@localhost',
    admin_password='admin123'
)

print(f'Admin user created:')
print(f'  Email: admin@localhost')
print(f'  Password: admin123')
print(f'  Tenant ID: {result[\"tenant_id\"]}')
print('')
print('⚠️  IMPORTANT: Change the admin password after first login!')
"

echo ""
echo "🎉 VPS Secure Compute Manager deployed successfully!"
echo ""
echo "📋 Installation Summary:"
echo "  • Infrastructure: ✅ Firecracker, LXC, Networking, Storage"
echo "  • Database: ✅ PostgreSQL with schema initialized"
echo "  • Web Server: ✅ Nginx reverse proxy with SSL"
echo "  • Services: ✅ SystemD service configured and running"
echo "  • Security: ✅ Firewall, SSL, security headers"
echo "  • Monitoring: ✅ Logging and log rotation"
echo ""
echo "🌐 Access Information:"
echo "  • Web Interface: https://your-domain.com (or https://localhost if testing)"
echo "  • API Documentation: https://your-domain.com/api/docs"
echo "  • Admin Login: admin@localhost / admin123"
echo ""
echo "🔧 Post-Installation Steps:"
echo "  1. Change admin password: systemctl status vps-secure-compute"
echo "  2. Update domain in nginx config: /etc/nginx/sites-available/vps-secure-compute"
echo "  3. Install proper SSL certificate (Let's Encrypt recommended)"
echo "  4. Configure DNS to point to this server"
echo "  5. Review and adjust quotas in /etc/vps-secure-compute/config.yaml"
echo ""
echo "📊 Service Management:"
echo "  • Start: systemctl start vps-secure-compute"
echo "  • Stop: systemctl stop vps-secure-compute"
echo "  • Status: systemctl status vps-secure-compute"
echo "  • Logs: journalctl -u vps-secure-compute -f"
echo ""
echo "🎯 Test Container Creation:"
echo "  vps-secure login admin@localhost"
echo "  vps-secure create-container --name test --template ubuntu-22.04"
echo ""