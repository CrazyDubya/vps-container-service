#!/usr/bin/env node

// Script to fix API key display issue
const fs = require('fs');

// Read auth-routes.js
const authRoutesPath = './lib/auth-routes.js';
let content = fs.readFileSync(authRoutesPath, 'utf8');

// Fix login endpoint - don't show API key on login
content = content.replace(
    /res\.json\({[\s]*message: 'Login successful',[\s]*user: {[\s]*id: user\.id,[\s]*username: user\.username,[\s]*email: user\.email,[\s]*role: user\.role,[\s]*apiKey: user\.api_key[\s]*},[\s]*token[\s]*}\);/,
    `res.json({
            message: 'Login successful',
            user: {
                id: user.id,
                username: user.username,
                email: user.email,
                role: user.role
            },
            token
        });`
);

// Fix profile endpoint - don't show hashed API key
content = content.replace(
    /res\.json\({[\s]*id: user\.id,[\s]*username: user\.username,[\s]*email: user\.email,[\s]*role: user\.role,[\s]*apiKey: user\.api_key,/,
    `res.json({
        id: user.id,
        username: user.username,
        email: user.email,
        role: user.role,`
);

fs.writeFileSync(authRoutesPath, content);
console.log('Fixed API key display in auth-routes.js');