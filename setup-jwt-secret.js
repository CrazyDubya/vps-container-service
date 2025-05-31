#!/usr/bin/env node

const fs = require('fs');
const crypto = require('crypto');
const path = require('path');

const envPath = path.join(__dirname, '.env');

// Check if .env exists
let envContent = '';
if (fs.existsSync(envPath)) {
    envContent = fs.readFileSync(envPath, 'utf8');
}

// Check if JWT_SECRET is already set
if (envContent.includes('JWT_SECRET=') && !envContent.includes('JWT_SECRET=\n') && !envContent.includes('JWT_SECRET=$')) {
    console.log('JWT_SECRET is already set in .env file');
    process.exit(0);
}

// Generate new JWT secret
const jwtSecret = crypto.randomBytes(32).toString('hex');

// Add or update JWT_SECRET in .env
if (envContent.includes('JWT_SECRET=')) {
    // Replace existing JWT_SECRET line
    envContent = envContent.replace(/JWT_SECRET=.*/g, `JWT_SECRET=${jwtSecret}`);
} else {
    // Add JWT_SECRET to the beginning
    envContent = `JWT_SECRET=${jwtSecret}\n${envContent}`;
}

// Write back to .env
fs.writeFileSync(envPath, envContent);

console.log('JWT_SECRET has been set in .env file');
console.log('Secret:', jwtSecret);