/**
 * Configuration Management
 */

const crypto = require('crypto');

class Config {
    constructor() {
        this.validateConfig();
    }

    validateConfig() {
        const errors = [];
        const warnings = [];

        // Required environment variables
        const required = ['JWT_SECRET'];
        required.forEach(key => {
            if (!process.env[key]) {
                errors.push(`Missing required environment variable: ${key}`);
            }
        });

        // JWT Secret validation
        if (process.env.JWT_SECRET && process.env.JWT_SECRET.length < 32) {
            warnings.push('JWT_SECRET should be at least 32 characters for security');
        }

        // Port validation
        const port = parseInt(process.env.PORT);
        if (port && (port < 1024 || port > 65535)) {
            warnings.push('PORT should be between 1024-65535');
        }

        // Admin password check
        if (!process.env.ADMIN_PASSWORD) {
            warnings.push('ADMIN_PASSWORD not set - using random generated password');
        } else if (process.env.ADMIN_PASSWORD.length < 8) {
            warnings.push('ADMIN_PASSWORD should be at least 8 characters');
        }

        // Backend type validation
        const validBackends = ['lxd', 'docker', 'lxc'];
        if (process.env.BACKEND_TYPE && !validBackends.includes(process.env.BACKEND_TYPE)) {
            errors.push(`Invalid BACKEND_TYPE: ${process.env.BACKEND_TYPE}. Valid options: ${validBackends.join(', ')}`);
        }

        // Container limits validation
        const maxContainers = parseInt(process.env.MAX_CONTAINERS_PER_USER);
        if (maxContainers && (maxContainers < 1 || maxContainers > 1000)) {
            warnings.push('MAX_CONTAINERS_PER_USER should be between 1-1000');
        }

        // TTL validation
        const ttl = parseInt(process.env.DEFAULT_CONTAINER_TTL);
        if (ttl && (ttl < 60 || ttl > 86400 * 7)) {
            warnings.push('DEFAULT_CONTAINER_TTL should be between 60 seconds and 7 days');
        }

        if (errors.length > 0) {
            console.error('❌ Configuration errors:');
            errors.forEach(error => console.error(`   ${error}`));
            throw new Error('Invalid configuration');
        }

        if (warnings.length > 0) {
            console.warn('⚠️  Configuration warnings:');
            warnings.forEach(warning => console.warn(`   ${warning}`));
        }
    }

    get() {
        return {
            // Server
            port: parseInt(process.env.PORT) || 3000,
            httpsPort: parseInt(process.env.HTTPS_PORT) || 3443,
            bindAddress: process.env.BIND_ADDRESS || '0.0.0.0',
            serverHost: process.env.SERVER_HOST || 'localhost',

            // Authentication
            jwtSecret: process.env.JWT_SECRET,
            jwtExpiry: process.env.JWT_EXPIRY || '24h',
            adminPassword: process.env.ADMIN_PASSWORD,

            // Container settings
            backendType: process.env.BACKEND_TYPE || 'lxd',
            maxContainersPerUser: parseInt(process.env.MAX_CONTAINERS_PER_USER) || 5,
            defaultContainerTTL: parseInt(process.env.DEFAULT_CONTAINER_TTL) || 3600,
            cleanupInterval: parseInt(process.env.CLEANUP_INTERVAL) || 300000,

            // WebSocket
            wsPath: process.env.WS_PATH || '/terminal',

            // Features
            enableAuditLog: process.env.ENABLE_AUDIT_LOG !== 'false',
            enableMetrics: process.env.ENABLE_METRICS === 'true',
        };
    }

    generateSecrets() {
        const secrets = {};

        if (!process.env.JWT_SECRET) {
            secrets.JWT_SECRET = crypto.randomBytes(32).toString('hex');
        }

        return secrets;
    }
}

module.exports = new Config();