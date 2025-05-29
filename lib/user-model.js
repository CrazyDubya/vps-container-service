const db = require('./database');
const bcrypt = require('bcrypt');

const saltRounds = 10; // Cost factor for bcrypt hashing

/**
 * Creates a new user in the database.
 * @param {string} username - The username.
 * @param {string} password - The plain text password.
 * @param {string} [role='user'] - The role of the user ('user' or 'admin').
 * @returns {Promise<object>} - A promise that resolves with the created user object (id, username, role).
 */
const createUser = async (username, password, role = 'user') => {
  // Basic validation
  if (!username || typeof username !== 'string' || username.length < 3 || username.length > 50) {
    throw new Error('Username must be a string between 3 and 50 characters.');
  }
  if (!/^[a-zA-Z0-9_.-]+$/.test(username)) {
    throw new Error('Username can only contain alphanumeric characters, underscores, dots, or hyphens.');
  }
  if (!password || typeof password !== 'string' || password.length < 8) {
    throw new Error('Password must be a string of at least 8 characters.');
  }
  if (role !== 'user' && role !== 'admin') {
    throw new Error("Role must be either 'user' or 'admin'.");
  }

  try {
    const passwordHash = await bcrypt.hash(password, saltRounds);
    
    return new Promise((resolve, reject) => {
      const stmt = db.prepare("INSERT INTO users (username, passwordHash, role) VALUES (?, ?, ?)");
      stmt.run(username, passwordHash, role, function(err) { // Use function keyword to get `this`
        if (err) {
          if (err.message && err.message.includes('UNIQUE constraint failed: users.username')) {
            return reject(new Error('Username already exists.'));
          }
          return reject(new Error(`Failed to create user: ${err.message}`));
        }
        resolve({ id: this.lastID, username, role });
      });
      stmt.finalize();
    });
  } catch (error) {
    // Catch bcrypt errors or other unexpected issues
    throw new Error(`Error creating user: ${error.message}`);
  }
};

/**
 * Finds a user by their username.
 * @param {string} username - The username to search for.
 * @returns {Promise<object|null>} - A promise that resolves with the user object or null if not found.
 */
const findUserByUsername = (username) => {
  return new Promise((resolve, reject) => {
    // COLLATE NOCASE in schema handles case-insensitivity for UNIQUE constraint,
    // but for querying, it's good practice to use LIKE or ensure the query matches this.
    // For simplicity and because of COLLATE NOCASE, direct comparison is often fine.
    // However, using `username = ? COLLATE NOCASE` in the query is more explicit.
    db.get("SELECT id, username, passwordHash, role, createdAt, updatedAt FROM users WHERE username = ? COLLATE NOCASE", [username], (err, row) => {
      if (err) {
        return reject(new Error(`Error finding user by username: ${err.message}`));
      }
      resolve(row || null);
    });
  });
};

/**
 * Finds a user by their ID.
 * @param {number} id - The ID of the user.
 * @returns {Promise<object|null>} - A promise that resolves with the user object or null if not found.
 */
const findUserById = (id) => {
  return new Promise((resolve, reject) => {
    db.get("SELECT id, username, role, createdAt, updatedAt FROM users WHERE id = ?", [id], (err, row) => {
      if (err) {
        return reject(new Error(`Error finding user by ID: ${err.message}`));
      }
      resolve(row || null);
    });
  });
};

/**
 * Verifies a plain text password against a hashed password.
 * @param {string} plainPassword - The plain text password.
 * @param {string} hashedPassword - The hashed password from the database.
 * @returns {Promise<boolean>} - A promise that resolves with true if passwords match, false otherwise.
 */
const verifyPassword = async (plainPassword, hashedPassword) => {
  if (!plainPassword || !hashedPassword) {
    return false; // Or throw an error, depending on desired strictness
  }
  try {
    return await bcrypt.compare(plainPassword, hashedPassword);
  } catch (error) {
    console.error("Error verifying password:", error);
    return false; // Should not happen with valid inputs to bcrypt.compare
  }
};

module.exports = {
  createUser,
  findUserByUsername,
  findUserById,
  verifyPassword,
  saltRounds // Export saltRounds if it might be useful elsewhere, e.g., testing
};
