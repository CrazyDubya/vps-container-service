#!/usr/bin/env node

// Quick fix for syntax errors
const fs = require('fs');

let content = fs.readFileSync('container-service-v2.js', 'utf8');

// Fix the broken container creation section
content = content.replace(
    /        }\);\s*\}\s*} else {\s*\/\/ Legacy limit checking[\s\S]*?}\s*}/,
    `        }`
);

// Remove duplicate return statements and fix limits endpoint
content = content.replace(
    /return res\.json\(\{[\s\S]*?\}\);\s*\/\/ Response sent above\s*res\.json\(\{[\s\S]*?\}\);/,
    `return res.json({
            maxContainers: MAX_CONTAINERS_PER_USER,
            currentContainers: userContainerCount,
            remaining: MAX_CONTAINERS_PER_USER - userContainerCount
        });`
);

// Write the updated content
fs.writeFileSync('container-service-v2.js', content);
console.log('Syntax errors fixed!');