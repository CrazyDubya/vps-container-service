#!/bin/bash

# Revert all absolute API URLs back to relative URLs to use worker proxy
sed -i "s|fetch(API_URL + '/auth/login'|fetch('/api/auth/login'|g" cloudflare-worker.js
sed -i "s|fetch(API_URL + '/auth/register'|fetch('/api/auth/register'|g" cloudflare-worker.js
sed -i "s|fetch(API_URL + '/auth/profile'|fetch('/api/auth/profile'|g" cloudflare-worker.js
sed -i "s|fetch(API_URL + '/auth/regenerate-api-key'|fetch('/api/auth/regenerate-api-key'|g" cloudflare-worker.js
sed -i "s|fetch(API_URL + '/containers/create'|fetch('/api/containers/create'|g" cloudflare-worker.js
sed -i "s|fetch(API_URL + '/containers'|fetch('/api/containers'|g" cloudflare-worker.js
sed -i "s|fetch(API_URL + '/auth/users'|fetch('/api/auth/users'|g" cloudflare-worker.js

# Fix template literal fetch calls
sed -i "s|fetch(\\\`\\\${API_URL}/containers/\\\${containerId}/status\\\`|fetch(\\\`/api/containers/\\\${containerId}/status\\\`|g" cloudflare-worker.js
sed -i "s|fetch(\\\`\\\${API_URL}/containers/\\\${containerId}/stop\\\`|fetch(\\\`/api/containers/\\\${containerId}/stop\\\`|g" cloudflare-worker.js
sed -i "s|fetch(\\\`\\\${API_URL}/containers/\\\${containerId}\\\`|fetch(\\\`/api/containers/\\\${containerId}\\\`|g" cloudflare-worker.js
sed -i "s|fetch(\\\`\\\${API_URL}/auth/users/\\\${userId}\\\`|fetch(\\\`/api/auth/users/\\\${userId}\\\`|g" cloudflare-worker.js

echo "Reverted to proxy URLs!"