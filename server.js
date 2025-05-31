#!/usr/bin/env node

/**
 * Container Service - Main Entry Point
 * 
 * A comprehensive container management service with:
 * - JWT/API key authentication
 * - Multi-backend support (LXD/Docker)
 * - Template-based container creation
 * - WebSocket terminals
 * - User management and audit logging
 */

require('dotenv').config();

// Validate required environment variables
const requiredEnvVars = ['JWT_SECRET'];
const missingVars = requiredEnvVars.filter(varName => !process.env[varName]);

if (missingVars.length > 0) {
    console.error('❌ Missing required environment variables:', missingVars.join(', '));
    console.error('💡 Run: node setup-jwt-secret.js to generate JWT_SECRET');
    process.exit(1);
}

console.log('🚀 Starting Container Service...');
console.log(`📦 Backend: ${process.env.BACKEND_TYPE || 'lxd'}`);
console.log(`🔐 Auth: JWT + API Keys`);

// Load and start the service
require('./container-service-v2');