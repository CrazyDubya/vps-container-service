# Port 443 Setup Guide

## Issue
Port 443 requires root privileges to bind. Our service runs as user `stephen`.

## Solutions

### Option 1: iptables Port Forwarding (Recommended)
```bash
# Forward port 443 to 3443 (requires root)
sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j REDIRECT --to-port 3443

# Make persistent
sudo iptables-save > /etc/iptables/rules.v4
```

### Option 2: systemd Service with Capabilities
Create `/etc/systemd/system/container-service.service`:
```ini
[Unit]
Description=Container Service
After=network.target

[Service]
Type=simple
User=stephen
WorkingDirectory=/home/stephen/vps-container-service
ExecStart=/usr/bin/node server.js
Environment=HTTPS_PORT=443
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=always

[Install]
WantedBy=multi-user.target
```

### Option 3: authbind (Allow non-root port binding)
```bash
# Install authbind
sudo apt install authbind

# Allow user to bind to port 443
sudo touch /etc/authbind/byport/443
sudo chown stephen:stephen /etc/authbind/byport/443
sudo chmod 755 /etc/authbind/byport/443

# Run service with authbind
authbind --deep node server.js
```

### Option 4: Reverse Proxy (nginx/apache)
```nginx
# /etc/nginx/sites-available/container-service
server {
    listen 443 ssl;
    server_name containers.conflost.com;
    
    ssl_certificate /home/stephen/vps-container-service/server.crt;
    ssl_certificate_key /home/stephen/vps-container-service/server.key;
    
    location / {
        proxy_pass https://127.0.0.1:3443;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /terminal {
        proxy_pass https://127.0.0.1:3443;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

## Current Status
- Service running on port 3443
- Direct access: `https://containers.conflost.com:3443`
- Cloudflare proxy disabled for custom port support

## Recommendation
Use **iptables forwarding** for immediate solution or **systemd with capabilities** for production deployment.