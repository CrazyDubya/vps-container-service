const jwt = require('jsonwebtoken');
const Database = require('./database');

const db = new Database();
const JWT_SECRET = process.env.JWT_SECRET || require('crypto').randomBytes(32).toString('hex');
const JWT_EXPIRY = process.env.JWT_EXPIRY || '24h';

// Warn if JWT secret is not set in environment
if (!process.env.JWT_SECRET) {
    console.warn('⚠️  WARNING: JWT_SECRET not found in environment variables');
    console.warn('⚠️  Using temporary secret - tokens will be invalid after restart');
    console.warn('⚠️  Run: node setup-jwt-secret.js to set a persistent secret');
}

// Authentication middleware for JWT tokens
const authenticateJWT = async (req, res, next) => {
    const authHeader = req.headers.authorization;
    
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
        return res.status(401).json({ error: 'Unauthorized: No token provided' });
    }
    
    const token = authHeader.split(' ')[1];
    
    try {
        const payload = jwt.verify(token, JWT_SECRET);
        const user = await db.getUserById(payload.userId);
        
        if (!user || !user.is_active) {
            return res.status(401).json({ error: 'Unauthorized: Invalid user' });
        }
        
        req.user = user;
        await db.logAction(user.id, 'api_access', req.path, null, req.ip);
        next();
    } catch (error) {
        if (error.name === 'TokenExpiredError') {
            return res.status(401).json({ error: 'Unauthorized: Token expired' });
        }
        return res.status(401).json({ error: 'Unauthorized: Invalid token' });
    }
};

// Authentication middleware for API keys
const authenticateApiKey = async (req, res, next) => {
    const apiKey = req.headers['x-api-key'];
    
    if (!apiKey) {
        return res.status(401).json({ error: 'Unauthorized: No API key provided' });
    }
    
    try {
        const user = await db.getUserByApiKey(apiKey);
        
        if (!user) {
            return res.status(401).json({ error: 'Unauthorized: Invalid API key' });
        }
        
        req.user = user;
        await db.logAction(user.id, 'api_access', req.path, null, req.ip);
        next();
    } catch (error) {
        return res.status(500).json({ error: 'Internal server error' });
    }
};

// Combined authentication - accepts either JWT or API key
const authenticate = async (req, res, next) => {
    const authHeader = req.headers.authorization;
    const apiKey = req.headers['x-api-key'];
    
    if (authHeader && authHeader.startsWith('Bearer ')) {
        return authenticateJWT(req, res, next);
    } else if (apiKey) {
        return authenticateApiKey(req, res, next);
    } else {
        return res.status(401).json({ error: 'Unauthorized: No credentials provided' });
    }
};

// Role-based access control middleware
const requireRole = (roles) => {
    return (req, res, next) => {
        if (!req.user) {
            return res.status(401).json({ error: 'Unauthorized' });
        }
        
        const userRoles = Array.isArray(roles) ? roles : [roles];
        if (!userRoles.includes(req.user.role)) {
            return res.status(403).json({ error: 'Forbidden: Insufficient permissions' });
        }
        
        next();
    };
};

// Generate JWT token
const generateToken = (userId) => {
    return jwt.sign({ userId }, JWT_SECRET, { expiresIn: JWT_EXPIRY });
};

// Verify JWT token (for non-middleware use)
const verifyToken = (token) => {
    try {
        return jwt.verify(token, JWT_SECRET);
    } catch (error) {
        return null;
    }
};

// Legacy API key authentication (for backward compatibility)
// Legacy authentication system removed - now using only JWT/API key system

module.exports = {
    authenticate,
    authenticateJWT,
    authenticateApiKey,
    requireRole,
    generateToken,
    verifyToken,
    db
};