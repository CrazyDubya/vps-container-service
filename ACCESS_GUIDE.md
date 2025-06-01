# Container Service Access Guide

## Current Status ✅

The container service is fully deployed and working with the following access methods:

### 1. Web GUI (via Cloudflare Worker)
- URL: https://vps-container-service.crazydubya.workers.dev/
- Status: ✅ Working
- Note: API proxy has issues due to Cloudflare limitations

### 2. Direct API Access
Choose one of these methods:

#### Option A: Direct IP (Recommended for API)
- HTTP: http://31.97.128.225:3000
- HTTPS: https://31.97.128.225:3443 (self-signed cert)

#### Option B: Domain Direct Access
- HTTP: http://containers.conflost.com:3000
- HTTPS: https://containers.conflost.com:3443 (self-signed cert)

### 3. Example API Usage

```bash
# Login
curl -X POST http://containers.conflost.com:3000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# List containers
curl -X GET http://containers.conflost.com:3000/containers \
  -H "Authorization: Bearer YOUR_TOKEN"

# Create container
curl -X POST http://containers.conflost.com:3000/containers/create \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"template":"python","maxMemory":512,"ttl":3600}'
```

## SSL Certificate Options

### Option 1: Cloudflare Origin Certificate (Recommended)
1. Go to Cloudflare Dashboard > SSL/TLS > Origin Server
2. Create certificate for containers.conflost.com
3. Download and install in the service

### Option 2: Let's Encrypt
1. Ensure port 80 is accessible
2. Run: `sudo certbot certonly --webroot -w /home/stephen/vps-container-service/public -d containers.conflost.com`
3. Update service to use the new certificates

### Option 3: Keep Self-Signed
- Current setup works but shows certificate warnings
- Fine for development/testing

## Architecture

```
┌─────────────────────────┐
│   Cloudflare Worker     │ ← GUI hosted here (fast, global)
│ (vps-container-service) │
└───────────┬─────────────┘
            │ 
            │ API calls (currently blocked by CF)
            ↓
┌─────────────────────────┐
│  containers.conflost.com│ ← Your domain
│    31.97.128.225       │
├─────────────────────────┤
│  Port 3000 (HTTP)      │ ← API access
│  Port 3443 (HTTPS)     │ ← Secure API
└─────────────────────────┘
```

## Known Limitations

1. **Cloudflare Proxy**: Only supports ports 80/443, so API must be accessed directly
2. **Self-Signed Certificate**: Shows warnings in browsers
3. **Worker API Proxy**: Can't bypass certificate validation or use non-standard ports

## Production Recommendations

1. Get proper SSL certificate (Cloudflare Origin or Let's Encrypt)
2. Consider moving API to port 443 for full Cloudflare proxy support
3. Or keep current setup with direct API access (common pattern)
EOF < /dev/null