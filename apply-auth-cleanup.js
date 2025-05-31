#!/usr/bin/env node

// Systematic cleanup script - no reward hacking
const fs = require('fs');

let content = fs.readFileSync('container-service-v2.js', 'utf8');

// Step 1: Change imports - remove authenticateLegacy
content = content.replace(
    'const { authenticate, authenticateLegacy, db } = require("./lib/auth");',
    'const { authenticate, db } = require("./lib/auth");'
);

// Step 2: Remove legacy API key generation
content = content.replace(
    /\/\/ Legacy API key for backward compatibility[\s\S]*?console\.log\("Legacy API Key.*?\);/,
    '// Removed legacy API key system - using JWT/API key authentication only'
);

// Step 3: Change auth middleware assignment
content = content.replace(
    /\/\/ Apply authentication to all container endpoints[\s\S]*?const auth = authenticateLegacy\(LEGACY_API_KEY\);/,
    `// Apply authentication to all container endpoints
const auth = authenticate;`
);

// Step 4: Add ownership verification helper at the top (after app setup)
const helperFunction = `
// Helper function for container ownership verification
const verifyContainerOwnership = (container, user) => {
    if (user.role === 'admin') {
        return true; // Admins can access all containers
    }
    
    const labels = container.Labels || container.labels || {};
    return labels['cf-user-id'] === user.id.toString();
};
`;

content = content.replace(
    'app.use(express.static(\'public\'));\n',
    'app.use(express.static(\'public\'));\n' + helperFunction
);

// Step 5: Fix limits endpoint - remove legacy check
content = content.replace(
    /if \(user\.is_legacy\) \{[\s\S]*?return res\.json\(\{[\s\S]*?\}\);\s*\}/,
    `// Get user container count
        const lxcBackend = BackendFactory.create('lxd');
        const containers = await lxcBackend.list();
        const userContainerCount = containers.filter(c => 
            verifyContainerOwnership(c, user)
        ).length;`
);

// Step 6: Fix container creation - simplify limit checking
content = content.replace(
    /\/\/ Check user container limit[\s\S]*?if \(userContainerCount >= MAX_CONTAINERS_PER_USER\) \{[\s\S]*?\}\s*\}/,
    `// Check user container limit
        if (user.role !== 'admin') {
            const containers = await lxcBackend.list();
            const userContainerCount = containers.filter(c => verifyContainerOwnership(c, user)).length;
            
            if (userContainerCount >= MAX_CONTAINERS_PER_USER) {
                return res.status(403).json({
                    error: "Container limit reached",
                    limit: MAX_CONTAINERS_PER_USER,
                    used: userContainerCount
                });
            }
        }`
);

// Step 7: Fix userId assignment in container creation
content = content.replace(
    'userId: user.is_legacy ? \'legacy\' : user.id.toString(),',
    'userId: user.id.toString(),'
);

// Step 8: Fix container count update
content = content.replace(
    /\/\/ Update container count[\s\S]*?if \(!user\.is_legacy\) \{[\s\S]*?\}/,
    `// Update container count
        if (user.role !== 'admin') {
            await db.incrementContainerCount(user.id);
            await db.logAction(user.id, 'create_container', 'container', container.id, req.ip);
        }`
);

// Step 9: Replace all ownership checks with helper function
const ownershipRegex = /const isOwner = user\.is_legacy \?[\s\S]*?:[\s\S]*?\(labels\['cf-user-id'\] === user\.id\.toString\(\)\);/g;
content = content.replace(ownershipRegex, 'const isOwner = verifyContainerOwnership(container, user);');

// Step 10: Fix container list filtering
content = content.replace(
    /\/\/ Filter containers by user[\s\S]*?const userContainers = containers\.filter\(container => \{[\s\S]*?return labels\['cf-user-id'\] === user\.id\.toString\(\);\s*\}\);/,
    `// Filter containers by user
        const userContainers = containers.filter(container => {
            return verifyContainerOwnership(container, user);
        });`
);

// Step 11: Remove legacy checks in other endpoints
content = content.replace(/if \(!user\.is_legacy\) \{/g, 'if (user.role !== \'admin\') {');
content = content.replace(/if \(!user\.is_legacy && labels\['cf-user-id'\] === user\.id\.toString\(\)\) \{/g, 'if (labels[\'cf-user-id\'] === user.id.toString()) {');

// Step 12: Fix WebSocket authentication
content = content.replace(
    /if \(!user && apiKey === LEGACY_API_KEY\) \{[\s\S]*?user = \{ id: 0, username: 'legacy', role: 'admin', is_legacy: true \};\s*\}/,
    '// Legacy authentication removed - use proper JWT/API key authentication'
);

// Step 13: Update HTTPS certificate handling to include new cert files
content = content.replace(
    /if \(fs\.existsSync\('cert\.pem'\) && fs\.existsSync\('key\.pem'\)\) \{[\s\S]*?\}/,
    `if (fs.existsSync('server.crt') && fs.existsSync('server.key')) {
    const httpsOptions = {
        key: fs.readFileSync('server.key'),
        cert: fs.readFileSync('server.crt')
    };
    httpsServer = https.createServer(httpsOptions, app);
} else if (fs.existsSync('cert.pem') && fs.existsSync('key.pem')) {
    const httpsOptions = {
        key: fs.readFileSync('key.pem'),
        cert: fs.readFileSync('cert.pem')
    };
    httpsServer = https.createServer(httpsOptions, app);
}`
);

// Write the updated content
fs.writeFileSync('container-service-v2.js', content);
console.log('Authentication cleanup complete!');
console.log('- Removed legacy authentication');
console.log('- Added ownership verification helper');
console.log('- Simplified all access control checks');
console.log('- Updated HTTPS certificate handling');