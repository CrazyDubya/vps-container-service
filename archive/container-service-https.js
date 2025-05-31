const fs = require('fs');
const https = require('https');
const path = require('path');

// Read the original service
const serviceCode = fs.readFileSync(path.join(__dirname, 'container-service-v2.js'), 'utf8');

// Replace the server creation and listening part
const modifiedCode = serviceCode
    .replace('const server = http.createServer(app);', `
const server = http.createServer(app);

// HTTPS server
const httpsOptions = {
    key: fs.readFileSync('key.pem'),
    cert: fs.readFileSync('cert.pem')
};
const httpsServer = https.createServer(httpsOptions, app);
    `)
    .replace('server.listen(PORT, "0.0.0.0", () => {', `
// Start both HTTP and HTTPS servers
server.listen(PORT, "0.0.0.0", () => {
    console.log(\`HTTP Container service running on port \${PORT}\`);
});

const HTTPS_PORT = process.env.HTTPS_PORT || 3443;
httpsServer.listen(HTTPS_PORT, "0.0.0.0", () => {
    console.log(\`HTTPS Container service running on port \${HTTPS_PORT}\`);
    console.log(\`\nAccess the service at:\`);
    console.log(\`  HTTP:  http://31.97.128.225:\${PORT}\`);
    console.log(\`  HTTPS: https://31.97.128.225:\${HTTPS_PORT}\`);
});

// Update WebSocket to work with HTTPS
const wssHttps = new WebSocket.Server({ 
    server: httpsServer, 
    path: '/terminal'
});

// Copy WebSocket handler for HTTPS
wssHttps.on('connection', wss.listeners('connection')[0]);

// Original HTTP server.listen
const originalListen = () => {`)
    .replace('});', '};');

// Fix the modified code
const finalCode = modifiedCode + '\n};';

eval(finalCode);