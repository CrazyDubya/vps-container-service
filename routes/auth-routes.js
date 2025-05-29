const express = require('express');
const jwt = require('jsonwebtoken');
const userModel = require('../lib/user-model');
const db = require('../lib/database'); // Required to query for existing users for first admin logic

const router = express.Router();

const JWT_SECRET = process.env.JWT_SECRET;
const TOKEN_EXPIRES_IN = process.env.TOKEN_EXPIRES_IN || '24h';

if (!JWT_SECRET) {
  console.error("CRITICAL: JWT_SECRET is not set in environment for auth-routes. This should have been caught on app startup.");
  process.exit(1); // Should not happen if container-service.js checks this
}

// Helper to count users - used for first user admin logic
const countUsers = () => {
  return new Promise((resolve, reject) => {
    db.get("SELECT COUNT(*) as count FROM users", (err, row) => {
      if (err) {
        return reject(new Error(`Error counting users: ${err.message}`));
      }
      resolve(row ? row.count : 0);
    });
  });
};

/**
 * @swagger
 * /auth/register:
 *   post:
 *     summary: Register a new user
 *     tags: [Auth]
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - username
 *               - password
 *             properties:
 *               username:
 *                 type: string
 *                 minLength: 3
 *                 maxLength: 50
 *               password:
 *                 type: string
 *                 minLength: 8
 *               role:
 *                 type: string
 *                 enum: [user, admin]
 *                 description: Optional. Defaults to 'user' unless it's the first user, who becomes 'admin'.
 *     responses:
 *       201:
 *         description: User registered successfully
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 id:
 *                   type: integer
 *                 username:
 *                   type: string
 *                 role:
 *                   type: string
 *       400:
 *         description: Invalid input (e.g., username taken, weak password, invalid role)
 *       500:
 *         description: Server error
 */
router.post('/register', async (req, res, next) => {
  const { username, password, role: requestedRole } = req.body;

  try {
    // Input validation (basic, more can be added with validator.js if desired)
    if (!username || username.length < 3 || username.length > 50) {
      return res.status(400).json({ error: 'Username must be 3-50 characters long.' });
    }
    if (!/^[a-zA-Z0-9_.-]+$/.test(username)) {
        return res.status(400).json({ error: 'Username can only contain alphanumeric characters, underscores, dots, or hyphens.' });
    }
    if (!password || password.length < 8) {
      return res.status(400).json({ error: 'Password must be at least 8 characters long.' });
    }
    if (requestedRole && requestedRole !== 'user' && requestedRole !== 'admin') {
      return res.status(400).json({ error: "Invalid role. Must be 'user' or 'admin'." });
    }

    const existingUser = await userModel.findUserByUsername(username);
    if (existingUser) {
      return res.status(400).json({ error: 'Username already exists.' });
    }

    let determinedRole = 'user';
    const totalUsers = await countUsers();
    
    if (totalUsers === 0) {
      determinedRole = 'admin'; // First user is always admin
      console.log(`Registering first user (${username}) as admin.`);
    } else if (requestedRole === 'admin') {
      // For now, we'll simplify: if a subsequent user explicitly requests 'admin',
      // they won't get it unless this logic is expanded for an existing admin to make this call.
      // This part will be secured later by an `authorizeRoles('admin')` middleware on a dedicated user management route.
      // For self-registration, non-first users are 'user'.
      console.warn(`User ${username} requested admin role during self-registration, but will be set to 'user' as they are not the first user.`);
      determinedRole = 'user'; 
    } else if (requestedRole) {
        determinedRole = requestedRole; // Respect 'user' if explicitly provided
    }


    const user = await userModel.createUser(username, password, determinedRole);
    res.status(201).json({
      message: 'User registered successfully.',
      user: { id: user.id, username: user.username, role: user.role },
    });
  } catch (error) {
    // Check for userModel specific errors (like username taken, if not caught above)
    if (error.message.includes('Username already exists') || error.message.includes('must be')) {
        return res.status(400).json({ error: error.message });
    }
    next(error); // Pass to centralized error handler
  }
});

/**
 * @swagger
 * /auth/login:
 *   post:
 *     summary: Log in a user
 *     tags: [Auth]
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - username
 *               - password
 *             properties:
 *               username:
 *                 type: string
 *               password:
 *                 type: string
 *     responses:
 *       200:
 *         description: Login successful
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 token:
 *                   type: string
 *       401:
 *         description: Invalid username or password
 *       500:
 *         description: Server error
 */
router.post('/login', async (req, res, next) => {
  const { username, password } = req.body;

  if (!username || !password) {
    return res.status(400).json({ error: 'Username and password are required.' });
  }

  try {
    const user = await userModel.findUserByUsername(username);
    if (!user) {
      return res.status(401).json({ error: 'Invalid username or password.' });
    }

    const isPasswordValid = await userModel.verifyPassword(password, user.passwordHash);
    if (!isPasswordValid) {
      return res.status(401).json({ error: 'Invalid username or password.' });
    }

    const tokenPayload = {
      userId: user.id,
      username: user.username,
      role: user.role,
    };

    const token = jwt.sign(tokenPayload, JWT_SECRET, { expiresIn: TOKEN_EXPIRES_IN });

    res.json({ token });
  } catch (error) {
    next(error); // Pass to centralized error handler
  }
});

module.exports = router;
