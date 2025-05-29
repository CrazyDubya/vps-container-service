const sqlite3 = require('sqlite3').verbose();
const path = require('path');

// Determine the database path. Store it in project root for simplicity.
// For production, consider a data directory outside the app code.
const dbPath = path.resolve(__dirname, '../cf_service.db');

// Initialize and export the database connection
// The database is opened in verbose mode for more detailed stack traces.
const db = new sqlite3.Database(dbPath, (err) => {
  if (err) {
    console.error('Could not connect to database', err.message);
  } else {
    console.log('Connected to SQLite database.');
  }
});

const initDb = () => {
  db.serialize(() => {
    // Create users table
    db.run(`
      CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL COLLATE NOCASE,
        passwordHash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'admin')),
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP
      );
    `, (err) => {
      if (err) {
        console.error("Error creating users table:", err.message);
      } else {
        console.log("Users table created or already exists.");
      }
    });

    // Create trigger for users.updatedAt
    db.run(`
      CREATE TRIGGER IF NOT EXISTS users_updated_at
      AFTER UPDATE ON users
      FOR EACH ROW
      BEGIN
          UPDATE users SET updatedAt = CURRENT_TIMESTAMP WHERE id = OLD.id;
      END;
    `, (err) => {
      if (err) {
        console.error("Error creating users_updated_at trigger:", err.message);
      } else {
        console.log("users_updated_at trigger created or already exists.");
      }
    });
  });
};

// Initialize the database schema when the module is loaded
initDb();

module.exports = db;
