const express = require("express");
const crypto = require("crypto");
const http = require("http");
const https = require("https");
const WebSocket = require("ws");
const cors = require("cors");
const multer = require("multer");
const fs = require("fs");
const path = require("path");
const BackendFactory = require("./lib/backend-factory");
const authRoutes = require("./lib/auth-routes");
const { authenticate, authenticateLegacy, db } = require("./lib/auth");

const app = express();
const server = http.createServer(app);

// HTTPS server setup
let httpsServer;
if (fs.existsSync('cert.pem') && fs.existsSync('key.pem')) {
    const httpsOptions = {
        key: fs.readFileSync('key.pem'),
        cert: fs.readFileSync('cert.pem')
    };
    httpsServer = https.createServer(httpsOptions, app);
}

app.use(express.json());
app.use(cors());
app.use(express.static('public'));

// Legacy API key for backward compatibility
const LEGACY_API_KEY = process.env.API_KEY || process.env.LEGACY_API_KEY || crypto.randomBytes(32).toString("hex");
console.log("Legacy API Key (for migration):", LEGACY_API_KEY);

// Create default admin password if needed
const initializeAuth = async () => {
    // This will create the default admin user if it doesn't exist
    const adminPassword = process.env.ADMIN_PASSWORD;
    if (!adminPassword) {
        console.log("\n⚠️  No ADMIN_PASSWORD set - check logs above for generated admin password");
        console.log("Set ADMIN_PASSWORD environment variable to use a custom password\n");
    }
};

initializeAuth();

// Mount auth routes
app.use('/auth', authRoutes);

// WebSocket server for interactive terminals
const wss = new WebSocket.Server({ 
    server, 
    path: '/terminal'
});

// Active terminal sessions
const terminalSessions = new Map();

// Container lifecycle management
const MAX_CONTAINERS_PER_USER = parseInt(process.env.MAX_CONTAINERS_PER_USER) || 5;
const DEFAULT_CONTAINER_TTL = parseInt(process.env.DEFAULT_CONTAINER_TTL) || 3600; // 1 hour
const CLEANUP_INTERVAL = parseInt(process.env.CLEANUP_INTERVAL) || 300000; // 5 minutes

// Cleanup expired containers
const cleanupExpiredContainers = async () => {
  try {
    const lxcBackend = BackendFactory.create('lxd');
    const containers = await lxcBackend.list();
    const now = new Date();
    
    for (const container of containers) {
      const labels = container.Labels || {};
      if (labels['cf-expires']) {
        const expires = new Date(labels['cf-expires']);
        if (expires < now) {
          console.log(`Cleaning up expired container: ${container.Names[0]}`);
          await lxcBackend.delete(container.Id);
          
          // Update user container count if user is tracked
          const userId = labels['cf-user-id'];
          if (userId) {
            await db.decrementContainerCount(parseInt(userId));
          }
        }
      }
    }
  } catch (error) {
    console.error('Cleanup error:', error.message);
  }
};

setInterval(cleanupExpiredContainers, CLEANUP_INTERVAL);

const PORT = process.env.PORT || 3000;
const HTTPS_PORT = process.env.HTTPS_PORT || 3443;

server.listen(PORT, "0.0.0.0", () => {
    console.log(`HTTP Container service running on port ${PORT}`);
    console.log(`WebSocket terminal available at ws://localhost:${PORT}/terminal`);
});

if (httpsServer) {
    httpsServer.listen(HTTPS_PORT, "0.0.0.0", () => {
        console.log(`HTTPS Container service running on port ${HTTPS_PORT}`);
        console.log(`WebSocket terminal available at wss://localhost:${HTTPS_PORT}/terminal`);
    });
}

console.log(`\nAuthentication endpoints:`);
console.log(`  POST /auth/register - Register new user`);
console.log(`  POST /auth/login - Login user`);
console.log(`  GET  /auth/profile - Get user profile`);
console.log(`\nAdmin endpoints:`);
console.log(`  GET  /auth/users - List all users`);
console.log(`  GET  /auth/audit-log - View audit log`);
console.log(`\nAccess URLs:`);
console.log(`  HTTP:  http://31.97.128.225:${PORT}`);
if (httpsServer) {
    console.log(`  HTTPS: https://31.97.128.225:${HTTPS_PORT}`);
}

// Service templates with enhanced configurations
const templates = {
    'ubuntu': {
        image: 'ubuntu:22.04',
        init: ['apt-get update', 'apt-get install -y curl wget vim nano htop'],
        env: ['DEBIAN_FRONTEND=noninteractive'],
        workdir: '/workspace'
    },
    'alpine': {
        image: 'alpine:latest',
        init: ['apk update', 'apk add --no-cache curl wget vim nano htop'],
        workdir: '/workspace'
    },
    'python': {
        image: 'python:3.11-slim',
        init: ['pip install --upgrade pip', 'pip install requests numpy pandas matplotlib jupyter ipython'],
        env: ['PYTHONUNBUFFERED=1'],
        workdir: '/workspace',
        volumes: [{name: 'pip-cache', path: '/root/.cache/pip'}]
    },
    'node': {
        image: 'node:20-slim',
        init: ['npm install -g yarn pnpm nodemon pm2'],
        env: ['NODE_ENV=development'],
        workdir: '/workspace',
        volumes: [{name: 'npm-cache', path: '/root/.npm'}]
    },
    'go': {
        image: 'golang:1.21-alpine',
        init: ['apk add --no-cache git make gcc musl-dev'],
        env: ['GO111MODULE=on', 'GOPROXY=https://proxy.golang.org'],
        workdir: '/workspace',
        volumes: [{name: 'go-modules', path: '/go/pkg/mod'}]
    },
    'rust': {
        image: 'rust:1.75-slim',
        init: ['apt-get update', 'apt-get install -y pkg-config libssl-dev'],
        env: ['RUST_BACKTRACE=1'],
        workdir: '/workspace',
        volumes: [{name: 'cargo-registry', path: '/usr/local/cargo/registry'}]
    },
    'java': {
        image: 'openjdk:21-slim',
        init: ['apt-get update', 'apt-get install -y maven gradle'],
        env: ['JAVA_TOOL_OPTIONS=-XX:+UseContainerSupport'],
        workdir: '/workspace',
        volumes: [{name: 'maven-repo', path: '/root/.m2'}]
    },
    'nginx': {
        image: 'nginx:alpine',
        init: ['apk add --no-cache curl'],
        workdir: '/usr/share/nginx/html',
        ports: {'80/tcp': null}
    },
    'apache': {
        image: 'httpd:2.4-alpine',
        init: ['apk add --no-cache curl'],
        workdir: '/usr/local/apache2/htdocs',
        ports: {'80/tcp': null}
    },
    'postgres': {
        image: 'postgres:15-alpine',
        env: ['POSTGRES_PASSWORD=postgres', 'POSTGRES_DB=myapp'],
        volumes: [{name: 'pgdata', path: '/var/lib/postgresql/data'}],
        ports: {'5432/tcp': null}
    },
    'redis': {
        image: 'redis:7-alpine',
        volumes: [{name: 'redis-data', path: '/data'}],
        ports: {'6379/tcp': null}
    },
    'pytorch': {
        image: 'pytorch/pytorch:latest',
        init: ['pip install jupyter matplotlib seaborn scikit-learn'],
        env: ['PYTHONUNBUFFERED=1'],
        workdir: '/workspace',
        volumes: [{name: 'models', path: '/models'}]
    },
    'tensorflow': {
        image: 'tensorflow/tensorflow:latest',
        init: ['pip install jupyter matplotlib seaborn scikit-learn'],
        env: ['PYTHONUNBUFFERED=1', 'TF_CPP_MIN_LOG_LEVEL=2'],
        workdir: '/workspace',
        volumes: [{name: 'models', path: '/models'}]
    }
};

// Health check endpoint
app.get("/health", (req, res) => {
    res.json({status: "healthy", timestamp: new Date().toISOString()});
});

// Apply authentication to all container endpoints
// Use legacy authentication for backward compatibility
const auth = authenticateLegacy(LEGACY_API_KEY);

// Get available templates
app.get("/templates", auth, (req, res) => {
    const templateList = Object.keys(templates).map(name => ({
        name,
        description: `${name} development environment`,
        image: templates[name].image
    }));
    res.json({templates: templateList});
});

// Get user limits and usage
app.get("/limits", auth, async (req, res) => {
    try {
        const user = req.user;
        
        if (user.is_legacy) {
            // Legacy response
            const lxcBackend = BackendFactory.create('lxd');
            const containers = await lxcBackend.list();
            const userContainerCount = containers.filter(c => 
                c.Labels && c.Labels['cf-user'] === 'legacy'
            ).length;
            
            return res.json({
                maxContainers: MAX_CONTAINERS_PER_USER,
                currentContainers: userContainerCount,
                remainingContainers: MAX_CONTAINERS_PER_USER - userContainerCount
            });
        }
        
        // New auth system response
        res.json({
            maxContainers: user.container_limit,
            currentContainers: user.containers_used,
            remainingContainers: user.container_limit - user.containers_used,
            username: user.username,
            role: user.role
        });
    } catch (error) {
        console.error('Limits error:', error);
        res.status(500).json({error: error.message});
    }
});

// Create container with template support
app.post("/containers/create", auth, async (req, res) => {
    try {
        const lxcBackend = BackendFactory.create('lxd');
        const user = req.user;
        
        // Check user container limit
        if (!user.is_legacy) {
            const canCreate = await db.canCreateContainer(user.id);
            if (!canCreate) {
                return res.status(403).json({
                    error: "Container limit reached",
                    limit: user.container_limit,
                    used: user.containers_used
                });
            }
        } else {
            // Legacy limit checking
            const containers = await lxcBackend.list();
            const userContainerCount = containers.filter(c => 
                c.Labels && c.Labels['cf-user'] === 'legacy'
            ).length;
            
            if (userContainerCount >= MAX_CONTAINERS_PER_USER) {
                return res.status(403).json({
                    error: "Container limit reached",
                    limit: MAX_CONTAINERS_PER_USER,
                    used: userContainerCount
                });
            }
        }
        
        // Get template or use custom config
        const template = req.body.template ? templates[req.body.template] : {};
        const config = {
            image: req.body.image || template.image || 'ubuntu:22.04',
            cmd: req.body.cmd || template.cmd,
            env: [...(template.env || []), ...(req.body.env || [])],
            workdir: req.body.workdir || template.workdir || '/workspace',
            volumes: [...(template.volumes || []), ...(req.body.volumes || [])],
            ports: {...(template.ports || {}), ...(req.body.ports || {})},
            memory: req.body.maxMemory || 512,
            ttl: req.body.ttl || DEFAULT_CONTAINER_TTL,
            userId: user.is_legacy ? 'legacy' : user.id.toString(),
            username: user.username || 'legacy',
            userRole: user.role || 'user'
        };
        
        const container = await lxcBackend.create(config);
        
        // Run initialization commands if specified
        if (template.init && template.init.length > 0) {
            for (const cmd of template.init) {
                try {
                    await lxcBackend.exec(container.id, cmd);
                } catch (initError) {
                    console.error(`Init command failed: ${cmd}`, initError.message);
                }
            }
        }
        
        // Update container count
        if (!user.is_legacy) {
            await db.incrementContainerCount(user.id);
            await db.logAction(user.id, 'create_container', 'container', container.id, req.ip);
        }
        
        res.json({
            id: container.id,
            name: container.name,
            status: "running",
            template: req.body.template || 'custom',
            expires: new Date(Date.now() + config.ttl * 1000).toISOString()
        });
    } catch (error) {
        console.error('Create container error:', error);
        res.status(500).json({error: error.message});
    }
});

// List containers (filtered by user)
app.get("/containers", auth, async (req, res) => {
    try {
        const lxcBackend = BackendFactory.create('lxd');
        const containers = await lxcBackend.list();
        const user = req.user;
        
        // Filter containers by user
        const userContainers = containers.filter(container => {
            const labels = container.Labels || {};
            if (user.is_legacy) {
                return labels['cf-user'] === 'legacy' || !labels['cf-user-id'];
            }
            return labels['cf-user-id'] === user.id.toString();
        });
        
        const containerList = userContainers.map(container => ({
            id: container.Id,
            name: container.Names[0].replace('/', ''),
            image: container.Image,
            status: container.State,
            created: new Date(container.Created * 1000).toISOString(),
            labels: container.Labels || {},
            ports: container.Ports || []
        }));
        
        res.json({containers: containerList});
    } catch (error) {
        console.error('List containers error:', error);
        res.status(500).json({error: error.message});
    }
});

// Get container info
app.get("/containers/:id", auth, async (req, res) => {
    try {
        const lxcBackend = BackendFactory.create('lxd');
        const user = req.user;
        
        // Verify container ownership
        const containers = await lxcBackend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = user.is_legacy ? 
            (labels['cf-user'] === 'legacy' || !labels['cf-user-id']) :
            (labels['cf-user-id'] === user.id.toString());
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        const info = await lxcBackend.inspect(req.params.id);
        
        res.json({
            id: info.Id,
            name: info.Name.replace('/', ''),
            image: info.Config.Image,
            status: info.State.Status,
            created: info.Created,
            started: info.State.StartedAt,
            labels: info.Config.Labels || {},
            env: info.Config.Env || [],
            ports: info.NetworkSettings.Ports || {},
            volumes: info.Mounts || []
        });
    } catch (error) {
        console.error('Get container error:', error);
        res.status(500).json({error: error.message});
    }
});

// Stop container
app.post("/containers/:id/stop", auth, async (req, res) => {
    try {
        const lxcBackend = BackendFactory.create('lxd');
        const user = req.user;
        
        // Verify ownership
        const containers = await lxcBackend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = user.is_legacy ? 
            (labels['cf-user'] === 'legacy' || !labels['cf-user-id']) :
            (labels['cf-user-id'] === user.id.toString());
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        await lxcBackend.stop(req.params.id);
        
        if (!user.is_legacy) {
            await db.logAction(user.id, 'stop_container', 'container', req.params.id, req.ip);
        }
        
        res.json({message: "Container stopped"});
    } catch (error) {
        console.error('Stop container error:', error);
        res.status(500).json({error: error.message});
    }
});

// Delete container
app.delete("/containers/:id", auth, async (req, res) => {
    try {
        const lxcBackend = BackendFactory.create('lxd');
        const user = req.user;
        
        // Verify ownership
        const containers = await lxcBackend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = user.is_legacy ? 
            (labels['cf-user'] === 'legacy' || !labels['cf-user-id']) :
            (labels['cf-user-id'] === user.id.toString());
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        await lxcBackend.delete(req.params.id);
        
        // Update container count
        if (!user.is_legacy && labels['cf-user-id'] === user.id.toString()) {
            await db.decrementContainerCount(user.id);
            await db.logAction(user.id, 'delete_container', 'container', req.params.id, req.ip);
        }
        
        res.json({message: "Container deleted"});
    } catch (error) {
        console.error('Delete container error:', error);
        res.status(500).json({error: error.message});
    }
});

// Execute command in container
app.post("/containers/:id/exec", auth, async (req, res) => {
    try {
        const lxcBackend = BackendFactory.create('lxd');
        const user = req.user;
        
        // Verify ownership
        const containers = await lxcBackend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = user.is_legacy ? 
            (labels['cf-user'] === 'legacy' || !labels['cf-user-id']) :
            (labels['cf-user-id'] === user.id.toString());
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        const result = await lxcBackend.exec(req.params.id, req.body.command);
        
        res.json({
            output: result.output,
            exitCode: result.exitCode
        });
    } catch (error) {
        console.error('Exec error:', error);
        res.status(500).json({error: error.message});
    }
});

// Get container logs
app.get("/containers/:id/logs", auth, async (req, res) => {
    try {
        const lxcBackend = BackendFactory.create('lxd');
        const user = req.user;
        
        // Verify ownership
        const containers = await lxcBackend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = user.is_legacy ? 
            (labels['cf-user'] === 'legacy' || !labels['cf-user-id']) :
            (labels['cf-user-id'] === user.id.toString());
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        const lines = parseInt(req.query.lines) || 100;
        const logs = await lxcBackend.logs(req.params.id, lines);
        
        res.json({logs});
    } catch (error) {
        console.error('Logs error:', error);
        res.status(500).json({error: error.message});
    }
});

// Get container stats
app.get("/containers/:id/stats", auth, async (req, res) => {
    try {
        const lxcBackend = BackendFactory.create('lxd');
        const user = req.user;
        
        // Verify ownership
        const containers = await lxcBackend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = user.is_legacy ? 
            (labels['cf-user'] === 'legacy' || !labels['cf-user-id']) :
            (labels['cf-user-id'] === user.id.toString());
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        const stats = await lxcBackend.stats(req.params.id);
        
        res.json({stats});
    } catch (error) {
        console.error('Stats error:', error);
        res.status(500).json({error: error.message});
    }
});

// File upload configuration
const upload = multer({
    dest: '/tmp/uploads/',
    limits: {
        fileSize: 10 * 1024 * 1024 // 10MB limit
    }
});

// Upload file to container
app.post("/containers/:id/files", auth, upload.single('file'), async (req, res) => {
    try {
        const lxcBackend = BackendFactory.create('lxd');
        const user = req.user;
        
        // Verify ownership
        const containers = await lxcBackend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = user.is_legacy ? 
            (labels['cf-user'] === 'legacy' || !labels['cf-user-id']) :
            (labels['cf-user-id'] === user.id.toString());
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        if (!req.file) {
            return res.status(400).json({error: "No file uploaded"});
        }
        
        const targetPath = req.body.path || `/workspace/${req.file.originalname}`;
        await lxcBackend.copyTo(req.params.id, req.file.path, targetPath);
        
        // Clean up temp file
        fs.unlinkSync(req.file.path);
        
        res.json({
            message: "File uploaded successfully",
            path: targetPath
        });
    } catch (error) {
        console.error('File upload error:', error);
        if (req.file && fs.existsSync(req.file.path)) {
            fs.unlinkSync(req.file.path);
        }
        res.status(500).json({error: error.message});
    }
});

// Download file from container
app.get("/containers/:id/files/*", auth, async (req, res) => {
    try {
        const lxcBackend = BackendFactory.create('lxd');
        const user = req.user;
        
        // Verify ownership
        const containers = await lxcBackend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = user.is_legacy ? 
            (labels['cf-user'] === 'legacy' || !labels['cf-user-id']) :
            (labels['cf-user-id'] === user.id.toString());
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        const filePath = '/' + req.params[0];
        const tempPath = `/tmp/download-${Date.now()}-${path.basename(filePath)}`;
        
        await lxcBackend.copyFrom(req.params.id, filePath, tempPath);
        
        res.download(tempPath, path.basename(filePath), (err) => {
            if (fs.existsSync(tempPath)) {
                fs.unlinkSync(tempPath);
            }
            if (err) {
                console.error('Download error:', err);
            }
        });
    } catch (error) {
        console.error('File download error:', error);
        res.status(500).json({error: error.message});
    }
});

// WebSocket terminal handler function
const handleWebSocketConnection = async (ws, req) => {
    const url = new URL(req.url, `http://${req.headers.host}`);
    const containerId = url.searchParams.get('container');
    const apiKey = url.searchParams.get('apiKey');
    const token = url.searchParams.get('token');
    
    // Authenticate WebSocket connection
    let user;
    if (token) {
        // JWT authentication
        const { verifyToken } = require('./lib/auth');
        const payload = verifyToken(token);
        if (!payload) {
            ws.send('Authentication failed');
            ws.close();
            return;
        }
        user = await db.getUserById(payload.userId);
    } else if (apiKey) {
        // API key authentication
        user = await db.getUserByApiKey(apiKey);
        if (!user && apiKey === LEGACY_API_KEY) {
            user = { id: 0, username: 'legacy', role: 'admin', is_legacy: true };
        }
    }
    
    if (!user) {
        ws.send('Authentication failed');
        ws.close();
        return;
    }
    
    if (!containerId) {
        ws.send('Container ID required');
        ws.close();
        return;
    }
    
    try {
        const lxcBackend = BackendFactory.create('lxd');
        
        // Verify container ownership
        const containers = await lxcBackend.list();
        const container = containers.find(c => c.Id.startsWith(containerId));
        
        if (!container) {
            ws.send('Container not found');
            ws.close();
            return;
        }
        
        const labels = container.Labels || {};
        const isOwner = user.is_legacy ? 
            (labels['cf-user'] === 'legacy' || !labels['cf-user-id']) :
            (labels['cf-user-id'] === user.id.toString());
        
        if (!isOwner && user.role !== 'admin') {
            ws.send('Access denied');
            ws.close();
            return;
        }
        
        const exec = await lxcBackend.attachInteractive(containerId);
        
        terminalSessions.set(ws, {
            exec,
            containerId,
            userId: user.id
        });
        
        // Forward data between WebSocket and container
        exec.output.on('data', (data) => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(data);
            }
        });
        
        ws.on('message', (data) => {
            exec.input.write(data);
        });
        
        ws.on('close', () => {
            terminalSessions.delete(ws);
            exec.input.end();
        });
        
    } catch (error) {
        console.error('WebSocket error:', error);
        ws.send(`Error: ${error.message}`);
        ws.close();
    }
};

// WebSocket terminal handling
wss.on('connection', handleWebSocketConnection);

// HTTPS WebSocket support
if (httpsServer) {
    const wssHttps = new WebSocket.Server({ 
        server: httpsServer, 
        path: '/terminal'
    });
    wssHttps.on('connection', handleWebSocketConnection);
}

// Graceful shutdown
process.on('SIGTERM', () => {
    console.log('Shutting down...');
    server.close(() => {
        db.close();
        process.exit(0);
    });
});