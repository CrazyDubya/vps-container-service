const express = require('express');
const { body, validationResult } = require('express-validator');
const { db, generateToken, authenticate, requireRole } = require('./auth');
const { createRateLimiter } = require('./rate-limit');

const router = express.Router();

const registerLimiter = createRateLimiter({
    windowMs: 60 * 60 * 1000,
    max: 5,
    message: 'Too many registration attempts; try again later'
});

const loginIpLimiter = createRateLimiter({
    windowMs: 15 * 60 * 1000,
    max: 30,
    message: 'Too many login attempts; try again later'
});

const loginAccountLimiter = createRateLimiter({
    windowMs: 15 * 60 * 1000,
    max: 10,
    keyFn: (req) => (req.body && typeof req.body.username === 'string' ? req.body.username.trim().toLowerCase() : 'missing'),
    message: 'Too many login attempts for this account; try again later'
});

const handleValidationErrors = (req, res, next) => {
    const errors = validationResult(req);
    if (!errors.isEmpty()) {
        return res.status(400).json({ errors: errors.array() });
    }
    next();
};

router.post('/register', registerLimiter, [
    body('username').isLength({ min: 3, max: 64 }).trim().escape(),
    body('email').isEmail().normalizeEmail(),
    body('password').isLength({ min: 12, max: 128 }),
    handleValidationErrors
], async (req, res) => {
    try {
        const { username, email, password } = req.body;

        const existingUser = await db.getUserByUsername(username);
        if (existingUser) {
            return res.status(409).json({ error: 'Username already exists' });
        }

        const existingEmail = await db.getUserByEmail(email);
        if (existingEmail) {
            return res.status(409).json({ error: 'Email already registered' });
        }

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

router.post('/login', loginIpLimiter, loginAccountLimiter, [
    body('username').isLength({ min: 1, max: 64 }).trim().escape(),
    body('password').isLength({ min: 1, max: 128 }),
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
        hasApiKey: !!user.api_key
    });
});

router.patch('/profile', authenticate, [
    body('email').optional().isEmail().normalizeEmail(),
    body('password').optional().isLength({ min: 12, max: 128 }),
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

router.patch('/users/:id', authenticate, requireRole('admin'), [
    body('email').optional().isEmail().normalizeEmail(),
    body('role').optional().isIn(['user', 'admin']),
    body('isActive').optional().isBoolean(),
    body('containerLimit').optional().isInt({ min: 0, max: 1000 }),
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

        res.json({ message: 'Profile updated successfully' });
    } catch (error) {
        console.error('Update user error:', error);
        res.status(500).json({ error: 'Failed to update user' });
    }
});

router.delete('/users/:id', authenticate, requireRole('admin'), async (req, res) => {
    try {
        const userId = req.params.id;

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

router.get('/audit-log', authenticate, requireRole('admin'), async (req, res) => {
    try {
        const { userId, limit = 100, offset = 0 } = req.query;
        const safeLimit = Math.min(500, Math.max(1, parseInt(limit) || 100));
        const safeOffset = Math.max(0, parseInt(offset) || 0);
        const logs = await db.getAuditLog({
            userId: userId ? parseInt(userId) : null,
            limit: safeLimit,
            offset: safeOffset
        });

        res.json({
            logs,
            pagination: {
                limit: safeLimit,
                offset: safeOffset
            }
        });
    } catch (error) {
        console.error('Audit log error:', error);
        res.status(500).json({ error: 'Failed to get audit log' });
    }
});

module.exports = router;
