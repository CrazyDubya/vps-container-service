#!/usr/bin/env node

// Script to remove legacy authentication references
const fs = require('fs');

let content = fs.readFileSync('container-service-v2.js', 'utf8');

// Remove legacy user checks - replace with proper user-based logic
const replacements = [
    // Fix limits endpoint
    {
        old: /if \(user\.is_legacy\) \{[\s\S]*?return res\.json\(\{[\s\S]*?\}\);[\s\S]*?\}/,
        new: `// Get user container count
        const lxcBackend = BackendFactory.create('lxd');
        const containers = await lxcBackend.list();
        const userContainerCount = containers.filter(c => 
            verifyContainerOwnership(c, user)
        ).length;
        
        return res.json({
            maxContainers: MAX_CONTAINERS_PER_USER,
            currentContainers: userContainerCount,
            remaining: MAX_CONTAINERS_PER_USER - userContainerCount
        });`
    },
    
    // Fix container creation user checks
    {
        old: /if \(!user\.is_legacy\) \{[\s\S]*?\}/g,
        new: `// Check container limit for regular users
        if (user.role !== 'admin') {
            const containers = await lxcBackend.list();
            const userContainerCount = containers.filter(c => verifyContainerOwnership(c, user)).length;
            
            if (userContainerCount >= MAX_CONTAINERS_PER_USER) {
                return res.status(400).json({
                    error: \`Container limit reached (\${MAX_CONTAINERS_PER_USER})\`
                });
            }
        }`
    },
    
    // Replace legacy ownership checks
    {
        old: /const isOwner = user\.is_legacy \?[\s\S]*?;/g,
        new: `const isOwner = verifyContainerOwnership(container, user);`
    },
    
    // Remove legacy user creation in WebSocket
    {
        old: /if \(!user && apiKey === LEGACY_API_KEY\) \{[\s\S]*?\}/,
        new: `// Legacy authentication removed - use proper JWT/API key authentication`
    },
    
    // Fix userId assignment
    {
        old: /userId: user\.is_legacy \? 'legacy' : user\.id\.toString\(\),/,
        new: `userId: user.id.toString(),`
    }
];

// Apply all replacements
replacements.forEach(({old, new: newStr}) => {
    content = content.replace(old, newStr);
});

// Write the updated content
fs.writeFileSync('container-service-v2.js', content);
console.log('Legacy authentication references removed!');