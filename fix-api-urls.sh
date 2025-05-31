#!/bin/bash

# Fix all relative API URLs to use absolute URLs with API_URL variable
sed -i "s|fetch('/api/auth/login'|fetch(API_URL + '/auth/login'|g" cloudflare-worker.js
sed -i "s|fetch('/api/auth/register'|fetch(API_URL + '/auth/register'|g" cloudflare-worker.js
sed -i "s|fetch('/api/auth/profile'|fetch(API_URL + '/auth/profile'|g" cloudflare-worker.js
sed -i "s|fetch('/api/auth/regenerate-api-key'|fetch(API_URL + '/auth/regenerate-api-key'|g" cloudflare-worker.js
sed -i "s|fetch('/api/containers/create'|fetch(API_URL + '/containers/create'|g" cloudflare-worker.js
sed -i "s|fetch('/api/containers'|fetch(API_URL + '/containers'|g" cloudflare-worker.js
sed -i "s|fetch('/api/auth/users'|fetch(API_URL + '/auth/users'|g" cloudflare-worker.js

# Fix template literal fetch calls
sed -i "s|fetch(\\\`/api/containers/\\\${containerId}/status\\\`|fetch(\\\`\\\${API_URL}/containers/\\\${containerId}/status\\\`|g" cloudflare-worker.js
sed -i "s|fetch(\\\`/api/containers/\\\${containerId}/stop\\\`|fetch(\\\`\\\${API_URL}/containers/\\\${containerId}/stop\\\`|g" cloudflare-worker.js
sed -i "s|fetch(\\\`/api/containers/\\\${containerId}\\\`|fetch(\\\`\\\${API_URL}/containers/\\\${containerId}\\\`|g" cloudflare-worker.js
sed -i "s|fetch(\\\`/api/auth/users/\\\${userId}\\\`|fetch(\\\`\\\${API_URL}/auth/users/\\\${userId}\\\`|g" cloudflare-worker.js

echo "Fixed all API URLs!"