const sqlite3 = require('sqlite3').verbose();
const bcrypt = require('bcrypt');
const crypto = require('crypto');
const path = require('path');

class Database {
    constructor(dbPath = path.join(__dirname, '..', 'users.db')) {
        this.db = new sqlite3.Database(dbPath);
        this.initializeDatabase();
    }

    initializeDatabase() {
        this.db.serialize(() => {
            // Users table
            this.db.run(`
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    api_key TEXT UNIQUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_login DATETIME,
                    is_active BOOLEAN DEFAULT 1,
                    container_limit INTEGER DEFAULT 5,
                    containers_used INTEGER DEFAULT 0
                )
            `);

            // API keys table for multiple keys per user
            this.db.run(`
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    key_hash TEXT UNIQUE NOT NULL,
                    name TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_used DATETIME,
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            `);

            // Sessions table
            this.db.run(`
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            `);

            // Audit log
            this.db.run(`
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    resource TEXT,
                    details TEXT,
                    ip_address TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            `);

            // Create default admin user if not exists
            this.createDefaultAdmin();
        });
    }

    async createDefaultAdmin() {
        const adminExists = await this.getUserByUsername('admin');
        if (!adminExists) {
            const defaultPassword = process.env.ADMIN_PASSWORD || crypto.randomBytes(16).toString('hex');
            console.log(`Creating default admin user with password: ${defaultPassword}`);
            await this.createUser({
                username: 'admin',
                email: 'admin@localhost',
                password: defaultPassword,
                role: 'admin',
                container_limit: 100
            });
        }
    }

    // User management
    async createUser(userData) {
        const { username, email, password, role = 'user', container_limit = 5 } = userData;
        const passwordHash = await bcrypt.hash(password, 10);
        const apiKey = crypto.randomBytes(32).toString('hex');
        
        return new Promise((resolve, reject) => {
            this.db.run(
                `INSERT INTO users (username, email, password_hash, role, api_key, container_limit) 
                 VALUES (?, ?, ?, ?, ?, ?)`,
                [username, email, passwordHash, role, apiKey, container_limit],
                function(err) {
                    if (err) reject(err);
                    else resolve({ id: this.lastID, username, email, role, apiKey });
                }
            );
        });
    }

    async getUserByUsername(username) {
        return new Promise((resolve, reject) => {
            this.db.get(
                'SELECT * FROM users WHERE username = ?',
                [username],
                (err, row) => {
                    if (err) reject(err);
                    else resolve(row);
                }
            );
        });
    }

    async getUserByEmail(email) {
        return new Promise((resolve, reject) => {
            this.db.get(
                'SELECT * FROM users WHERE email = ?',
                [email],
                (err, row) => {
                    if (err) reject(err);
                    else resolve(row);
                }
            );
        });
    }

    async getUserById(id) {
        return new Promise((resolve, reject) => {
            this.db.get(
                'SELECT * FROM users WHERE id = ?',
                [id],
                (err, row) => {
                    if (err) reject(err);
                    else resolve(row);
                }
            );
        });
    }

    async getUserByApiKey(apiKey) {
        return new Promise((resolve, reject) => {
            this.db.get(
                'SELECT * FROM users WHERE api_key = ? AND is_active = 1',
                [apiKey],
                (err, row) => {
                    if (err) reject(err);
                    else resolve(row);
                }
            );
        });
    }

    async validatePassword(username, password) {
        const user = await this.getUserByUsername(username);
        if (!user || !user.is_active) return null;
        
        const isValid = await bcrypt.compare(password, user.password_hash);
        if (isValid) {
            await this.updateLastLogin(user.id);
            return user;
        }
        return null;
    }

    async updateLastLogin(userId) {
        return new Promise((resolve, reject) => {
            this.db.run(
                'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?',
                [userId],
                (err) => {
                    if (err) reject(err);
                    else resolve();
                }
            );
        });
    }

    async updateUser(userId, updates) {
        const allowedFields = ['email', 'role', 'is_active', 'container_limit'];
        const fields = Object.keys(updates).filter(f => allowedFields.includes(f));
        const values = fields.map(f => updates[f]);
        values.push(userId);
        
        const query = `UPDATE users SET ${fields.map(f => `${f} = ?`).join(', ')} WHERE id = ?`;
        
        return new Promise((resolve, reject) => {
            this.db.run(query, values, (err) => {
                if (err) reject(err);
                else resolve();
            });
        });
    }

    async changePassword(userId, newPassword) {
        const passwordHash = await bcrypt.hash(newPassword, 10);
        return new Promise((resolve, reject) => {
            this.db.run(
                'UPDATE users SET password_hash = ? WHERE id = ?',
                [passwordHash, userId],
                (err) => {
                    if (err) reject(err);
                    else resolve();
                }
            );
        });
    }

    async regenerateApiKey(userId) {
        const newApiKey = crypto.randomBytes(32).toString('hex');
        return new Promise((resolve, reject) => {
            this.db.run(
                'UPDATE users SET api_key = ? WHERE id = ?',
                [newApiKey, userId],
                (err) => {
                    if (err) reject(err);
                    else resolve(newApiKey);
                }
            );
        });
    }

    // Container tracking
    async incrementContainerCount(userId) {
        return new Promise((resolve, reject) => {
            this.db.run(
                'UPDATE users SET containers_used = containers_used + 1 WHERE id = ?',
                [userId],
                (err) => {
                    if (err) reject(err);
                    else resolve();
                }
            );
        });
    }

    async decrementContainerCount(userId) {
        return new Promise((resolve, reject) => {
            this.db.run(
                'UPDATE users SET containers_used = MAX(0, containers_used - 1) WHERE id = ?',
                [userId],
                (err) => {
                    if (err) reject(err);
                    else resolve();
                }
            );
        });
    }

    async canCreateContainer(userId) {
        const user = await this.getUserById(userId);
        return user && user.containers_used < user.container_limit;
    }

    // List users (admin only)
    async listUsers(options = {}) {
        const { limit = 50, offset = 0, role = null } = options;
        let query = 'SELECT id, username, email, role, created_at, last_login, is_active, container_limit, containers_used FROM users';
        const params = [];
        
        if (role) {
            query += ' WHERE role = ?';
            params.push(role);
        }
        
        query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?';
        params.push(limit, offset);
        
        return new Promise((resolve, reject) => {
            this.db.all(query, params, (err, rows) => {
                if (err) reject(err);
                else resolve(rows);
            });
        });
    }

    // Audit logging
    async logAction(userId, action, resource = null, details = null, ipAddress = null) {
        return new Promise((resolve, reject) => {
            this.db.run(
                'INSERT INTO audit_log (user_id, action, resource, details, ip_address) VALUES (?, ?, ?, ?, ?)',
                [userId, action, resource, details, ipAddress],
                (err) => {
                    if (err) reject(err);
                    else resolve();
                }
            );
        });
    }

    async getAuditLog(options = {}) {
        const { userId = null, limit = 100, offset = 0 } = options;
        let query = 'SELECT * FROM audit_log';
        const params = [];
        
        if (userId) {
            query += ' WHERE user_id = ?';
            params.push(userId);
        }
        
        query += ' ORDER BY timestamp DESC LIMIT ? OFFSET ?';
        params.push(limit, offset);
        
        return new Promise((resolve, reject) => {
            this.db.all(query, params, (err, rows) => {
                if (err) reject(err);
                else resolve(rows);
            });
        });
    }

    close() {
        this.db.close();
    }
}

module.exports = Database;