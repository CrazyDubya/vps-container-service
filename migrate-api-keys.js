#!/usr/bin/env node

// Migration script to hash existing API keys
const sqlite3 = require('sqlite3').verbose();
const bcrypt = require('bcrypt');
const path = require('path');

const dbPath = path.join(__dirname, 'users.db');
const db = new sqlite3.Database(dbPath);

console.log('Starting API key migration...');

// First, let's check if we need to migrate
db.all('SELECT id, username, api_key FROM users WHERE api_key IS NOT NULL', async (err, rows) => {
    if (err) {
        console.error('Error reading users:', err);
        process.exit(1);
    }
    
    let needsMigration = false;
    
    // Check if any API keys are not hashed (hashed keys start with $2b$)
    for (const row of rows) {
        if (row.api_key && !row.api_key.startsWith('$2b$')) {
            needsMigration = true;
            break;
        }
    }
    
    if (!needsMigration) {
        console.log('All API keys are already hashed. No migration needed.');
        db.close();
        process.exit(0);
    }
    
    console.log(`Found ${rows.length} users to check for migration`);
    
    // Create backup table
    db.run(`CREATE TABLE IF NOT EXISTS users_backup AS SELECT * FROM users`, (err) => {
        if (err) {
            console.error('Error creating backup:', err);
            process.exit(1);
        }
        
        console.log('Created backup table');
        
        // Migrate each user's API key
        let migrated = 0;
        let errors = 0;
        
        const promises = rows.map(row => {
            return new Promise(async (resolve) => {
                if (row.api_key && !row.api_key.startsWith('$2b$')) {
                    try {
                        // Hash the API key
                        const hashedKey = await bcrypt.hash(row.api_key, 10);
                        
                        // Update the database
                        db.run('UPDATE users SET api_key = ? WHERE id = ?', [hashedKey, row.id], (err) => {
                            if (err) {
                                console.error(`Error updating user ${row.username}:`, err);
                                errors++;
                            } else {
                                console.log(`✓ Migrated API key for user: ${row.username}`);
                                migrated++;
                            }
                            resolve();
                        });
                    } catch (hashError) {
                        console.error(`Error hashing API key for user ${row.username}:`, hashError);
                        errors++;
                        resolve();
                    }
                } else {
                    resolve();
                }
            });
        });
        
        Promise.all(promises).then(() => {
            console.log('\nMigration complete:');
            console.log(`- Migrated: ${migrated} users`);
            console.log(`- Errors: ${errors}`);
            console.log('\nBackup table created: users_backup');
            console.log('To restore: DROP TABLE users; ALTER TABLE users_backup RENAME TO users;');
            
            db.close();
            process.exit(errors > 0 ? 1 : 0);
        });
    });
});