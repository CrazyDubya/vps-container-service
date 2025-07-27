#!/usr/bin/env node

const Database = require('./lib/database');

async function setupTestUser() {
    const db = new Database();
    
    const testApiKey = 'test-api-key-for-automated-testing';
    const testUsername = 'testuser';
    const testEmail = 'test@example.com';
    const testPassword = 'testpass123';
    
    try {
        // Check if test user already exists
        const existingUser = await new Promise((resolve, reject) => {
            db.db.get('SELECT * FROM users WHERE username = ? OR api_key = ?', 
                [testUsername, testApiKey], (err, row) => {
                if (err) reject(err);
                else resolve(row);
            });
        });
        
        if (existingUser) {
            console.log('Test user already exists - updating to admin user and container limit...');
            // Update role and container limit
            await new Promise((resolve, reject) => {
                db.db.run('UPDATE users SET container_limit = ?, role = ? WHERE username = ?', 
                    [5, 'admin', testUsername], (err) => {
                    if (err) reject(err);
                    else resolve();
                });
            });
            console.log('✅ Test user updated successfully');
            return;
        }
        
        // Create test user
        const user = await db.createUser({
            username: testUsername,
            email: testEmail,
            password: testPassword,
            role: 'admin',
            container_limit: 5
        });
        
        // Set API key for test user
        await new Promise((resolve, reject) => {
            db.db.run('UPDATE users SET api_key = ? WHERE id = ?', 
                [testApiKey, user.id], (err) => {
                if (err) reject(err);
                else resolve();
            });
        });
        
        console.log('✅ Test user created successfully');
        console.log(`Username: ${testUsername}`);
        console.log(`API Key: ${testApiKey}`);
        console.log(`User ID: ${user.id}`);
        
    } catch (error) {
        console.error('❌ Failed to create test user:', error);
        process.exit(1);
    } finally {
        db.close();
    }
}

if (require.main === module) {
    setupTestUser();
}

module.exports = setupTestUser;