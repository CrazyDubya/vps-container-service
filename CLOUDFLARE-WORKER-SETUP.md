# 🚀 Cloudflare Worker Deployment Guide

This guide shows how to deploy the Container Service GUI as a Cloudflare Worker, replacing LocalTunnel with a more reliable and professional solution.

## 📋 Prerequisites

1. **Cloudflare Account** (free tier works)
2. **Your Server Running** on a public IP (currently: `31.97.128.225:3000`)
3. **Wrangler CLI** installed globally

## 🛠️ Setup Steps

### 1. Install Wrangler CLI

```bash
npm install -g wrangler
```

### 2. Login to Cloudflare

```bash
wrangler auth login
```

### 3. Update Server IP in Worker

Edit `cloudflare-worker.js` and update your server IP:

```javascript
// Your server configuration
const BACKEND_SERVER = 'http://YOUR_ACTUAL_IP:3000'; // Replace with your server IP
const BACKEND_SERVER_HTTPS = 'https://YOUR_ACTUAL_IP:3443'; // HTTPS endpoint
```

### 4. Create Wrangler Configuration

Create `wrangler.toml`:

```toml
name = "vps-container-service"
main = "cloudflare-worker.js"
compatibility_date = "2024-01-01"

[env.production]
name = "vps-container-service"
```

### 5. Deploy to Cloudflare Workers

```bash
# Deploy to production
wrangler deploy

# Or deploy to a specific subdomain
wrangler deploy --name your-custom-name
```

## 🌍 Custom Domain (Optional)

### Option 1: Using Workers Custom Domain

1. Go to **Cloudflare Dashboard** → **Workers & Pages**
2. Click your worker → **Settings** → **Triggers**
3. Add **Custom Domain**: `containers.yourdomain.com`

### Option 2: Using Workers Route

1. Add your domain to Cloudflare DNS
2. Create a **Worker Route** in your domain's dashboard
3. Route pattern: `containers.yourdomain.com/*`
4. Select your worker

## 🔧 Configuration Options

### Environment Variables

You can set environment variables in `wrangler.toml`:

```toml
[env.production.vars]
BACKEND_SERVER = "http://your-server-ip:3000"
BACKEND_SERVER_HTTPS = "https://your-server-ip:3443"
```

Then update the worker to use them:

```javascript
const BACKEND_SERVER = env.BACKEND_SERVER || 'http://31.97.128.225:3000';
const BACKEND_SERVER_HTTPS = env.BACKEND_SERVER_HTTPS || 'https://31.97.128.225:3443';
```

### CORS Configuration

The worker automatically adds CORS headers for cross-origin requests:

```javascript
'Access-Control-Allow-Origin': '*',
'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
'Access-Control-Allow-Headers': 'Content-Type, Authorization, x-api-key',
```

## 📡 How It Works

### Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   User Browser  │───▶│ Cloudflare      │───▶│  Your Server    │
│                 │    │ Worker (GUI)    │    │ (API Backend)   │
│ containers.     │    │                 │    │ 31.97.128.225   │
│ yourdomain.com  │    │ - Serves HTML   │    │ :3000/:3443     │
│                 │    │ - Proxies APIs  │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Request Flow

1. **Static Requests** (`/`, `/index.html`) → Serves embedded HTML
2. **API Requests** (`/api/*`) → Proxies to your backend server
3. **WebSocket** (`/api/terminal`) → Returns connection instructions

### Benefits vs LocalTunnel

| Feature | LocalTunnel | Cloudflare Worker |
|---------|-------------|-------------------|
| **Reliability** | ❌ Often disconnects | ✅ 99.9% uptime |
| **Speed** | ❌ Slow routing | ✅ Edge locations |
| **Custom Domain** | ❌ Random subdomains | ✅ Your domain |
| **SSL/HTTPS** | ⚠️ Basic | ✅ Enterprise-grade |
| **Caching** | ❌ No caching | ✅ Intelligent caching |
| **Cost** | 🆓 Free but limited | 🆓 100k requests/day free |

## 🚀 Deployment Commands

```bash
# Quick deployment
wrangler deploy

# Preview before deploying
wrangler dev

# Deploy with custom name
wrangler deploy --name my-container-service

# Check deployment status
wrangler deployments list

# View logs
wrangler tail
```

## 🔍 Testing Your Deployment

After deployment, test these endpoints:

```bash
# GUI (should load the web interface)
curl https://your-worker.your-subdomain.workers.dev/

# Health check (should proxy to your server)
curl https://your-worker.your-subdomain.workers.dev/api/health

# API example
curl -X POST https://your-worker.your-subdomain.workers.dev/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username": "admin", "password": "admin123"}'
```

## 🛡️ Security Considerations

### 1. Server IP Protection

The worker proxies requests, hiding your server IP from clients.

### 2. CORS Security

Configure CORS based on your needs:

```javascript
// Restrict to specific origins
'Access-Control-Allow-Origin': 'https://your-domain.com',

// Or allow all (current setup)
'Access-Control-Allow-Origin': '*',
```

### 3. Rate Limiting

Add rate limiting to the worker:

```javascript
// Simple rate limiting example
const RATE_LIMIT = 100; // requests per minute
const rateLimitKey = request.headers.get('CF-Connecting-IP');
// Implement rate limiting logic
```

## 🔧 Advanced Customization

### 1. Caching Strategy

```javascript
// Cache static assets
if (url.pathname.endsWith('.css') || url.pathname.endsWith('.js')) {
  response.headers.set('Cache-Control', 'public, max-age=86400'); // 24 hours
}
```

### 2. Analytics

```javascript
// Add basic analytics
if (url.pathname === '/') {
  // Log page views
  console.log('Page view from:', request.headers.get('CF-Connecting-IP'));
}
```

### 3. Authentication Caching

```javascript
// Cache user sessions
const cache = caches.default;
const cacheKey = new Request(url.toString(), request);
let response = await cache.match(cacheKey);
```

## 🎯 Next Steps

1. **Deploy the worker** using the commands above
2. **Update your server CORS** to allow the worker domain
3. **Test all functionality** through the worker
4. **Set up monitoring** with Cloudflare Analytics
5. **Configure custom domain** if desired

## 📞 Support

If you encounter issues:

1. Check **Wrangler logs**: `wrangler tail`
2. Verify **server accessibility**: `curl http://your-server-ip:3000/health`
3. Test **CORS settings** with browser dev tools
4. Check **Cloudflare Dashboard** for worker metrics

---

**🎉 Your container service is now running on Cloudflare's global edge network!**