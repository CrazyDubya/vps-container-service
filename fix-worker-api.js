// Quick fix script to update API URLs in the worker

const fs = require('fs');

// Read the worker file
let content = fs.readFileSync('cloudflare-worker.js', 'utf8');

// Fix the API_URL definition
content = content.replace(
    'const API_URL = \'https://31.97.128.225:3443\';  // Direct connection to backend',
    `// Auto-detect API URL for hybrid architecture
        let API_URL;
        if (typeof window !== 'undefined') {
            // Browser context - use direct backend connection
            API_URL = 'https://31.97.128.225:3443';
        } else {
            // Worker context - not used for API calls
            API_URL = 'https://31.97.128.225:3443';
        }`
);

// Fix all the broken template literals
content = content.replace(/\$\{API_URL\}/g, '${API_URL}');

// Save the fixed file
fs.writeFileSync('cloudflare-worker.js', content);

console.log('Worker API URLs fixed!');