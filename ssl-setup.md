# SSL Certificate Setup Guide

## Option 1: Let's Encrypt with Certbot (Requires root access)

### Install Certbot:
```bash
sudo apt update
sudo apt install certbot
```

### Generate Certificate:
```bash
# Stop the current service first
sudo systemctl stop container-service

# Generate certificate using standalone mode
sudo certbot certonly --standalone \
  -d containers.conflost.com \
  --email your-email@domain.com \
  --agree-tos \
  --non-interactive

# Copy certificates to service directory
sudo cp /etc/letsencrypt/live/containers.conflost.com/fullchain.pem /home/stephen/vps-container-service/server.crt
sudo cp /etc/letsencrypt/live/containers.conflost.com/privkey.pem /home/stephen/vps-container-service/server.key
sudo chown stephen:stephen /home/stephen/vps-container-service/server.*

# Restart service
node server.js
```

### Auto-renewal Setup:
```bash
# Add to crontab
sudo crontab -e

# Add this line for automatic renewal:
0 2 * * * certbot renew --quiet --post-hook "systemctl restart container-service"
```

## Option 2: Manual DNS Challenge (Current Setup)

Since we don't have root access, we can use DNS challenge method:

### Generate Certificate Request:
```bash
# Generate private key
openssl genrsa -out server.key 2048

# Generate certificate signing request
openssl req -new -key server.key -out server.csr \
  -subj "/C=US/ST=State/L=City/O=Organization/CN=containers.conflost.com"

# Generate self-signed certificate (temporary)
openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt
```

### For Let's Encrypt DNS Challenge:
1. Create account key: `openssl genrsa 4096 > account.key`
2. Use acme.sh or similar tool for DNS challenge
3. Add DNS TXT record to prove domain ownership
4. Generate certificate

## Option 3: Cloudflare Origin Certificate

Since domain is on Cloudflare, we can use Origin Certificates:

1. Go to Cloudflare Dashboard → SSL/TLS → Origin Server
2. Create Origin Certificate
3. Select "Let Cloudflare generate a private key and a CSR"
4. Add hostnames: `containers.conflost.com`
5. Download certificate and private key
6. Save as `server.crt` and `server.key`

## Current Status

The service is currently running with self-signed certificates on:
- HTTPS: `https://containers.conflost.com:3443`
- Domain resolves directly to: `31.97.128.225`
- Cloudflare proxy: Disabled for custom port support

## Recommended Approach

For production use:
1. **Cloudflare Origin Certificate** (easiest with current setup)
2. **Let's Encrypt with DNS challenge** (most standard)
3. **Move to port 443** and re-enable Cloudflare proxy for full SSL termination