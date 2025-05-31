# 🚀 Quick Deployment Guide

## Step 1: Install Wrangler CLI
```bash
npm install -g wrangler
```

## Step 2: Login with Your Credentials
```bash
wrangler auth login
# If that doesn't work, use your API token:
export CLOUDFLARE_API_TOKEN="FvXs81afG3WqtKeW7YdZ3M0aHH3lVY7tVG5F9Mom"
```

## Step 3: Deploy Immediately
```bash
cd /home/stephen/vps-container-service
wrangler deploy
```

## Step 4: Test Your Deployment
After deployment, you'll get a URL like:
```
https://vps-container-service.your-subdomain.workers.dev
```

Visit that URL and you should see your container service GUI!

## Step 5: API Examples
```bash
# Replace with your actual worker URL
WORKER_URL="https://vps-container-service.your-subdomain.workers.dev"

# Test health endpoint
curl "$WORKER_URL/api/health"

# Test login
curl -X POST "$WORKER_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

## 🎯 What You Get

✅ **Professional URL** instead of random LocalTunnel subdomain  
✅ **99.9% uptime** via Cloudflare's edge network  
✅ **Global CDN** for fast loading worldwide  
✅ **SSL/HTTPS** automatically enabled  
✅ **No more tunnel disconnections**  
✅ **Custom domain** support if needed

Your container service is now running on Cloudflare Workers! 🎉