# 🔧 Manual Cloudflare Worker Deployment

Since automatic deployment isn't working, here's how to deploy manually through the Cloudflare Dashboard:

## 📋 Method 1: Cloudflare Dashboard (Recommended)

### Step 1: Login to Cloudflare Dashboard
1. Go to [https://dash.cloudflare.com/](https://dash.cloudflare.com/)
2. Login with your account

### Step 2: Navigate to Workers
1. Click **"Workers & Pages"** in the left sidebar
2. Click **"Create Application"**
3. Choose **"Create Worker"**

### Step 3: Deploy the Worker
1. **Name your worker**: `vps-container-service`
2. Click **"Deploy"**
3. Click **"Edit Code"** in the new worker

### Step 4: Copy the Worker Code
1. **Delete all existing code** in the editor
2. **Copy the entire contents** of `cloudflare-worker.js` 
3. **Paste it** into the editor
4. **Update the IP address** in lines 7-8:
   ```javascript
   const DEFAULT_BACKEND_SERVER = 'http://31.97.128.225:3000';
   const DEFAULT_BACKEND_SERVER_HTTPS = 'https://31.97.128.225:3443';
   ```
   Replace `31.97.128.225` with your actual server IP if different.

### Step 5: Save and Deploy
1. Click **"Save and Deploy"**
2. Wait for deployment to complete
3. Note your worker URL: `https://vps-container-service.YOUR-SUBDOMAIN.workers.dev`

## 📋 Method 2: Wrangler CLI (If you have a working token)

### Step 1: Create API Token
1. Go to [Cloudflare Dashboard → My Profile → API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Click **"Create Token"**
3. Use **"Edit Cloudflare Workers"** template
4. Configure:
   - **Permissions**: `Zone:Zone Settings:Edit`, `Zone:Zone:Read`, `User:User Details:Read`
   - **Account Resources**: Include your account
   - **Zone Resources**: Include all zones
5. Copy the new token

### Step 2: Deploy with Wrangler
```bash
cd /home/stephen/vps-container-service
export CLOUDFLARE_API_TOKEN="your-new-token-here"
npx wrangler deploy
```

## 🌍 Method 3: Custom Domain (Optional)

### Add Custom Domain
1. In Worker dashboard, go to **Settings → Triggers**
2. Click **"Add Custom Domain"**
3. Enter your domain: `containers.yourdomain.com`
4. Follow DNS setup instructions

## 🧪 Testing Your Deployment

### Test the GUI
Visit your worker URL:
```
https://vps-container-service.YOUR-SUBDOMAIN.workers.dev
```

You should see the container service login page.

### Test API Endpoints
```bash
# Replace with your actual worker URL
WORKER_URL="https://vps-container-service.YOUR-SUBDOMAIN.workers.dev"

# Health check
curl "$WORKER_URL/api/health"

# Login test
curl -X POST "$WORKER_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

### Test Container Creation
1. **Login** via the web interface
2. **Click "Create Container"**
3. **Choose a template** (Python, Node.js, etc.)
4. **Watch the progress bar** - this tests the async functionality
5. **Verify** container appears in the list

## 🔧 Configuration

### Environment Variables (Optional)
In the Worker dashboard:
1. Go to **Settings → Variables**
2. Add environment variables:
   - `BACKEND_SERVER`: `http://your-server-ip:3000`
   - `BACKEND_SERVER_HTTPS`: `https://your-server-ip:3443`

### CORS Configuration
The worker automatically handles CORS. If you need to restrict origins:

Edit the worker code and change:
```javascript
'Access-Control-Allow-Origin': '*',
```
to:
```javascript
'Access-Control-Allow-Origin': 'https://your-domain.com',
```

## 📊 Monitoring

### View Analytics
1. In Worker dashboard, click **"Analytics"**
2. Monitor:
   - Request count
   - Error rate
   - Response time
   - CPU usage

### View Logs
1. Click **"Logs"** tab
2. Use **"Tail Workers"** for real-time logs
3. Debug any issues with API proxying

## ✅ Success Checklist

- [ ] Worker deployed successfully
- [ ] GUI loads at worker URL
- [ ] Login/register works
- [ ] API endpoints respond correctly
- [ ] Container creation shows progress
- [ ] No CORS errors in browser console
- [ ] Backend server accessible from worker

## 🚨 Troubleshooting

### Common Issues

**1. "Backend server unavailable"**
- Check your server IP in the worker code
- Verify your server is running: `curl http://your-ip:3000/health`
- Check firewall settings

**2. CORS errors**
- Worker automatically adds CORS headers
- Check browser console for specific errors
- Verify API endpoints use `/api/` prefix

**3. Authentication issues**
- Ensure backend is accessible
- Check server logs for auth errors
- Verify JWT tokens are working

**4. Container creation fails**
- Test container creation directly: `curl http://your-ip:3000/containers/create`
- Check LXD service status
- Verify image availability

## 🎯 Next Steps

1. **Custom domain** (optional): Add `containers.yourdomain.com`
2. **SSL certificate** (automatic with Cloudflare)
3. **Rate limiting** (configure in Cloudflare dashboard)
4. **Analytics setup** (already enabled)
5. **Monitoring alerts** (set up in Cloudflare)

---

**🎉 Your container service is now globally available via Cloudflare Workers!**

No more LocalTunnel disconnections - your service is now professional-grade! 🚀