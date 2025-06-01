const express = require('express');
const { body, validationResult } = require('express-validator');
const { db, generateToken, authenticate, requireRole } = require('./auth');

const router = express.Router();

// Validation middleware
const handleValidationErrors = (req, res, next) => {
    const errors = validationResult(req);
    if (!errors.isEmpty()) {
        return res.status(400).json({ errors: errors.array() });
    }
    next();
};

// Public endpoints

// User registration
router.post('/register', [
    body('username').isLength({ min: 3 }).trim().escape(),
    body('email').isEmail().normalizeEmail(),
    body('password').isLength({ min: 8 }),
    handleValidationErrors
], async (req, res) => {
    try {
        const { username, email, password } = req.body;
        
        // Check if user already exists
        const existingUser = await db.getUserByUsername(username);
        if (existingUser) {
            return res.status(409).json({ error: 'Username already exists' });
        }
        
        const existingEmail = await db.getUserByEmail(email);
        if (existingEmail) {
            return res.status(409).json({ error: 'Email already registered' });
        }
        
        // Create user
        const user = await db.createUser({ username, email, password });
        const token = generateToken(user.id);
        
        await db.logAction(user.id, 'register', null, null, req.ip);
        
        res.status(201).json({
            message: 'User created successfully',
            user: {
                id: user.id,
                username: user.username,
                email: user.email,
                role: user.role,
                apiKey: user.apiKey
            },
            token
        });
    } catch (error) {
        console.error('Registration error:', error);
        res.status(500).json({ error: 'Failed to create user' });
    }
});

// User login
router.post('/login', [
    body('username').notEmpty().trim().escape(),
    body('password').notEmpty(),
    handleValidationErrors
], async (req, res) => {
    try {
        const { username, password } = req.body;
        
        const user = await db.validatePassword(username, password);
        if (!user) {
            await db.logAction(null, 'failed_login', null, username, req.ip);
            return res.status(401).json({ error: 'Invalid credentials' });
        }
        
        const token = generateToken(user.id);
        await db.logAction(user.id, 'login', null, null, req.ip);
        
        res.json({
            message: 'Login successful',
            user: {
                id: user.id,
                username: user.username,
                email: user.email,
                role: user.role
            },
            token
        });
    } catch (error) {
        console.error('Login error:', error);
        res.status(500).json({ error: 'Login failed' });
    }
});

// Protected endpoints

// Get current user profile
router.get('/profile', authenticate, async (req, res) => {
    const user = req.user;
    res.json({
        id: user.id,
        username: user.username,
        email: user.email,
        role: user.role,
        containerLimit: user.container_limit,
        containersUsed: user.containers_used,
        createdAt: user.created_at,
        lastLogin: user.last_login,
        hasApiKey: !!user.api_key // Only indicate if user has an API key
    });
});

// Update profile
router.patch('/profile', authenticate, [
    body('email').optional().isEmail().normalizeEmail(),
    body('password').optional().isLength({ min: 8 }),
    handleValidationErrors
], async (req, res) => {
    try {
        const userId = req.user.id;
        const { email, password } = req.body;
        
        if (email) {
            const existingEmail = await db.getUserByEmail(email);
            if (existingEmail && existingEmail.id !== userId) {
                return res.status(409).json({ error: 'Email already in use' });
            }
            await db.updateUser(userId, { email });
        }
        
        if (password) {
            await db.changePassword(userId, password);
        }
        
        await db.logAction(userId, 'profile_update', null, null, req.ip);
        
        res.json({ message: 'Profile updated successfully' });
    } catch (error) {
        console.error('Profile update error:', error);
        res.status(500).json({ error: 'Failed to update profile' });
    }
});

// Regenerate API key
router.post('/regenerate-api-key', authenticate, async (req, res) => {
    try {
        const newApiKey = await db.regenerateApiKey(req.user.id);
        await db.logAction(req.user.id, 'regenerate_api_key', null, null, req.ip);
        
        res.json({
            message: 'API key regenerated successfully',
            apiKey: newApiKey
        });
    } catch (error) {
        console.error('API key regeneration error:', error);
        res.status(500).json({ error: 'Failed to regenerate API key' });
    }
});

// Admin endpoints

// List all users (admin only)
router.get('/users', authenticate, requireRole('admin'), async (req, res) => {
    try {
        const { limit = 50, offset = 0, role } = req.query;
        const users = await db.listUsers({ limit: parseInt(limit), offset: parseInt(offset), role });
        
        res.json({
            users,
            pagination: {
                limit: parseInt(limit),
                offset: parseInt(offset)
            }
        });
    } catch (error) {
        console.error('List users error:', error);
        res.status(500).json({ error: 'Failed to list users' });
    }
});

// Get specific user (admin only)
router.get('/users/:id', authenticate, requireRole('admin'), async (req, res) => {
    try {
        const user = await db.getUserById(req.params.id);
        if (!user) {
            return res.status(404).json({ error: 'User not found' });
        }
        
        res.json({
            id: user.id,
            username: user.username,
            email: user.email,
            role: user.role,
            containerLimit: user.container_limit,
            containersUsed: user.containers_used,
            isActive: user.is_active,
            createdAt: user.created_at,
            lastLogin: user.last_login
        });
    } catch (error) {
        console.error('Get user error:', error);
        res.status(500).json({ error: 'Failed to get user' });
    }
});

// Update user (admin only)
router.patch('/users/:id', authenticate, requireRole('admin'), [
    body('email').optional().isEmail().normalizeEmail(),
    body('role').optional().isIn(['user', 'admin']),
    body('isActive').optional().isBoolean(),
    body('containerLimit').optional().isInt({ min: 0 }),
    handleValidationErrors
], async (req, res) => {
    try {
        const userId = req.params.id;
        const updates = {};
        
        if (req.body.email !== undefined) updates.email = req.body.email;
        if (req.body.role !== undefined) updates.role = req.body.role;
        if (req.body.isActive !== undefined) updates.is_active = req.body.isActive;
        if (req.body.containerLimit !== undefined) updates.container_limit = req.body.containerLimit;
        
        await db.updateUser(userId, updates);
        await db.logAction(req.user.id, 'update_user', 'user', userId, req.ip);
        
        res.json({ message: 'User updated successfully' });
    } catch (error) {
        console.error('Update user error:', error);
        res.status(500).json({ error: 'Failed to update user' });
    }
});

// Delete user (admin only)
router.delete('/users/:id', authenticate, requireRole('admin'), async (req, res) => {
    try {
        const userId = req.params.id;
        
        // Prevent deleting self
        if (userId == req.user.id) {
            return res.status(400).json({ error: 'Cannot delete your own account' });
        }
        
        await db.updateUser(userId, { is_active: false });
        await db.logAction(req.user.id, 'delete_user', 'user', userId, req.ip);
        
        res.json({ message: 'User deactivated successfully' });
    } catch (error) {
        console.error('Delete user error:', error);
        res.status(500).json({ error: 'Failed to delete user' });
    }
});

// Get audit log (admin only)
router.get('/audit-log', authenticate, requireRole('admin'), async (req, res) => {
    try {
        const { userId, limit = 100, offset = 0 } = req.query;
        const logs = await db.getAuditLog({
            userId: userId ? parseInt(userId) : null,
            limit: parseInt(limit),
            offset: parseInt(offset)
        });
        
        res.json({
            logs,
            pagination: {
                limit: parseInt(limit),
                offset: parseInt(offset)
            }
        });
    } catch (error) {
        console.error('Audit log error:', error);
        res.status(500).json({ error: 'Failed to get audit log' });
    }
});

module.exports = router;