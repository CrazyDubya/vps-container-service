require('dotenv').config();

const express = require("express");
const crypto = require("crypto");
const http = require("http");
const https = require("https");
const WebSocket = require("ws");
const cors = require("cors");
const multer = require("multer");
const fs = require("fs");
const path = require("path");
const backendManager = require("./lib/backend-manager");
const authRoutes = require("./lib/auth-routes");
const { authenticate, db } = require("./lib/auth");
const { getTemplate, listTemplates, getTemplatesByCategory, validateTemplate } = require("./lib/templates");
const { asyncHandler, errorHandler, validateOwnership, validateContainerLimit, NotFoundError, LimitExceededError } = require("./lib/error-handler");
const hotContainerManager = require("./lib/hot-containers");
const cacheManager = require("./lib/cache-manager");

const app = express();
const server = http.createServer(app);

// HTTPS server setup
let httpsServer;
if (fs.existsSync('server.crt') && fs.existsSync('server.key')) {
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
}

app.use(express.json());
app.use(cors());
app.use(express.static('public'));

// Helper function for container ownership verification
const verifyContainerOwnership = (container, user) => {
    if (user.role === 'admin') {
        return true; // Admins can access all containers
    }
    
    const labels = container.Labels || container.labels || {};
    return labels['cf-user-id'] === user.id.toString();
};

// Removed legacy API key system - using JWT/API key authentication only

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

// Initialize hot container system
hotContainerManager.initialize().catch(error => {
    console.error('Failed to initialize hot containers:', error.message);
});

// Initialize cache system
cacheManager.initialize().catch(error => {
    console.error('Failed to initialize cache:', error.message);
});

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

// Backend configuration
const BACKEND_TYPE = process.env.BACKEND_TYPE || 'lxd';

// Cleanup expired containers
const cleanupExpiredContainers = async () => {
  try {
    const backend = backendManager.getDefaultBackend();
    const containers = await backend.list();
    const now = new Date();
    
    for (const container of containers) {
      const labels = container.Labels || {};
      if (labels['cf-expires']) {
        const expires = new Date(labels['cf-expires']);
        if (expires < now) {
          console.log(`Cleaning up expired container: ${container.Names[0]}`);
          await backend.delete(container.Id);
          
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
const HTTP_PORT = process.env.HTTP_PORT || 80;
const HTTPS_PORT = process.env.HTTPS_PORT || 3443;
const BIND_ADDRESS = process.env.BIND_ADDRESS || "0.0.0.0";
const SERVER_HOST = process.env.SERVER_HOST || "localhost";

// Start on port 3000 (current)
server.listen(PORT, BIND_ADDRESS, () => {
    console.log(`HTTP Container service running on port ${PORT}`);
    console.log(`WebSocket terminal available at ws://${SERVER_HOST}:${PORT}${process.env.WS_PATH || '/terminal'}`);
});

// Also start on port 80 for standard HTTP and Let's Encrypt
const httpServer80 = http.createServer(app);
httpServer80.listen(HTTP_PORT, BIND_ADDRESS, () => {
    console.log(`HTTP service also running on port ${HTTP_PORT} (standard HTTP)`);
}).on('error', (err) => {
    if (err.code === 'EACCES') {
        console.log(`⚠️  Port ${HTTP_PORT} requires root privileges. Run with sudo or use port 3000`);
    } else if (err.code === 'EADDRINUSE') {
        console.log(`ℹ️  Port ${HTTP_PORT} already in use. Using port ${PORT} only.`);
    }
});

if (httpsServer) {
    httpsServer.listen(HTTPS_PORT, BIND_ADDRESS, () => {
        console.log(`HTTPS Container service running on port ${HTTPS_PORT}`);
        console.log(`WebSocket terminal available at wss://${SERVER_HOST}:${HTTPS_PORT}${process.env.WS_PATH || '/terminal'}`);
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
console.log(`  HTTP:  http://${SERVER_HOST}:${PORT}`);
console.log(`  HTTP:  http://${SERVER_HOST}/ (standard port, if available)`);
if (httpsServer) {
    console.log(`  HTTPS: https://${SERVER_HOST}:${HTTPS_PORT}`);
}

// Templates now managed centrally in lib/templates.js

// Health check endpoint
app.get("/health", (req, res) => {
    res.json({status: "healthy", timestamp: new Date().toISOString()});
});

// Apply authentication to all container endpoints
const auth = authenticate;

// Get available templates
app.get("/templates", auth, asyncHandler(async (req, res) => {
    const cacheKey = 'templates:formatted';
    
    const templates = await cacheManager.getOrSet(cacheKey, () => {
        const templatesByCategory = getTemplatesByCategory();
        const templateList = listTemplates();
        
        return {
            templates: templateList,
            categories: templatesByCategory
        };
    }, 3600); // Cache for 1 hour
    
    res.json(templates);
}));

// Get hot container pool status (admin only)
app.get("/admin/hot-containers", auth, (req, res) => {
    if (req.user.role !== 'admin') {
        return res.status(403).json({error: "Admin access required"});
    }
    
    const status = hotContainerManager.getPoolStatus();
    res.json({
        pools: status,
        timestamp: new Date().toISOString()
    });
});

// Get user limits and usage
app.get("/limits", auth, async (req, res) => {
    try {
        const user = req.user;
        
        // Get user container count
        const backend = backendManager.getDefaultBackend();
        const containers = await backend.list();
        const userContainerCount = containers.filter(c => 
            verifyContainerOwnership(c, user)
        ).length;
        
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
app.post("/containers/create", auth, asyncHandler(async (req, res) => {
    const backend = backendManager.getDefaultBackend();
    const user = req.user;
    
    // Check user container limit
    if (user.role !== 'admin') {
        const containers = await backend.list();
        const userContainerCount = containers.filter(c => verifyContainerOwnership(c, user)).length;
        
        validateContainerLimit(userContainerCount, MAX_CONTAINERS_PER_USER, user.username);
    }
        
        // Validate and merge template configuration
        let config;
        if (req.body.template) {
            config = validateTemplate(req.body.template, req.body);
        } else {
            // Custom configuration without template
            config = {
                image: req.body.image || 'ubuntu:22.04',
                cmd: req.body.cmd,
                env: req.body.env || [],
                workdir: req.body.workdir || '/workspace',
                volumes: req.body.volumes || [],
                ports: req.body.ports || {},
                maxMemory: req.body.maxMemory || 512,
                init: []
            };
        }
        
        // Add system configuration
        config.ttl = req.body.ttl || DEFAULT_CONTAINER_TTL;
        config.userId = user.id.toString();
        config.username = user.username;
        config.userRole = user.role;
        config.template = req.body.template;
        
        // Try to get a hot container first for faster provisioning
        let container = null;
        if (req.body.template) {
            container = await hotContainerManager.getHotContainer(
                req.body.template, 
                user.id.toString(), 
                user.username, 
                user.role
            );
        }
        
        // If no hot container available, create normally
        if (!container) {
            container = await backend.create(config);
        }
        
        // Template initialization is now handled by the backend during creation
        
        // Update container count
        if (user.role !== 'admin') {
            await db.incrementContainerCount(user.id);
            await db.logAction(user.id, 'create_container', 'container', container.id || container, req.ip);
        }
        
        // Invalidate user's container cache
        await cacheManager.invalidateUserCache(user.id);
        
    // Handle both string ID and object response from backend
    const containerId = typeof container === 'string' ? container : container.id;
    const containerName = typeof container === 'string' ? containerId.substring(0, 12) : container.name;
    
    res.json({
        id: containerId,
        name: containerName,
        status: "running",
        template: req.body.template || 'custom',
        expires: new Date(Date.now() + config.ttl * 1000).toISOString(),
        volumes: config.volumes || []
    });
}));

// List containers (filtered by user)
app.get("/containers", auth, async (req, res) => {
    try {
        const user = req.user;
        const cacheKey = `containers:${user.id}`;
        
        // Try to get from cache first
        const cachedContainers = await cacheManager.getCachedContainerList(user.id);
        if (cachedContainers) {
            return res.json({containers: cachedContainers});
        }
        
        const backend = backendManager.getDefaultBackend();
        const containers = await backend.list();
        
        // Filter containers by user
        const userContainers = containers.filter(container => {
            return verifyContainerOwnership(container, user);
        });
        
        const containerList = userContainers.map(container => ({
            id: container.id || container.Id,
            name: container.name || (container.Names && container.Names[0] ? container.Names[0].replace('/', '') : 'unknown'),
            image: container.image || container.Image,
            status: container.status || container.State,
            created: container.created || (container.Created ? new Date(container.Created * 1000).toISOString() : new Date().toISOString()),
            labels: container.labels || container.Labels || {},
            ports: container.ports || container.Ports || []
        }));
        
        // Cache the result for 30 seconds (dynamic data)
        await cacheManager.cacheContainerList(user.id, containerList);
        
        res.json({containers: containerList});
    } catch (error) {
        console.error('List containers error:', error);
        res.status(500).json({error: error.message});
    }
});

// Get container info
app.get("/containers/:id", auth, async (req, res) => {
    try {
        const backend = backendManager.getDefaultBackend();
        const user = req.user;
        
        // Verify container ownership
        const containers = await backend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = verifyContainerOwnership(container, user);
        
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

// Get container creation status (for progress tracking)
app.get("/containers/:id/status", auth, async (req, res) => {
    try {
        const backend = backendManager.getDefaultBackend();
        const user = req.user;
        
        // Verify ownership
        const containers = await backend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            // Container might still be creating
            return res.json({
                status: 'creating',
                progress: 40,
                message: 'Container is being created...'
            });
        }
        
        const isOwner = verifyContainerOwnership(container, user);
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        // Container exists and is ready
        res.json({
            status: 'ready',
            progress: 100,
            message: 'Container is ready!',
            container: {
                id: container.Id,
                name: container.Names[0].replace('/', ''),
                status: container.State
            }
        });
    } catch (error) {
        console.error('Container status error:', error);
        res.json({
            status: 'failed',
            progress: 100,
            error: error.message
        });
    }
});

// Stop container
app.post("/containers/:id/stop", auth, async (req, res) => {
    try {
        const backend = backendManager.getDefaultBackend();
        const user = req.user;
        
        // Verify ownership
        const containers = await backend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = verifyContainerOwnership(container, user);
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        await lxcBackend.stop(req.params.id);
        
        if (user.role !== 'admin') {
            await db.logAction(user.id, 'stop_container', 'container', req.params.id, req.ip);
        }
        
        // Invalidate cache for this container and user
        await cacheManager.invalidateContainerCache(req.params.id, user.id);
        
        res.json({message: "Container stopped"});
    } catch (error) {
        console.error('Stop container error:', error);
        res.status(500).json({error: error.message});
    }
});

// Delete container
app.delete("/containers/:id", auth, async (req, res) => {
    try {
        const backend = backendManager.getDefaultBackend();
        const user = req.user;
        
        // Verify ownership
        const containers = await backend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = verifyContainerOwnership(container, user);
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        await lxcBackend.delete(req.params.id);
        
        // Update container count
        if (labels['cf-user-id'] === user.id.toString()) {
            await db.decrementContainerCount(user.id);
            await db.logAction(user.id, 'delete_container', 'container', req.params.id, req.ip);
        }
        
        // Invalidate cache for this container and user
        await cacheManager.invalidateContainerCache(req.params.id, user.id);
        
        res.json({message: "Container deleted"});
    } catch (error) {
        console.error('Delete container error:', error);
        res.status(500).json({error: error.message});
    }
});

// Execute command in container
app.post("/containers/:id/exec", auth, async (req, res) => {
    try {
        const backend = backendManager.getDefaultBackend();
        const user = req.user;
        
        // Verify ownership
        const containers = await backend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = verifyContainerOwnership(container, user);
        
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
        const backend = backendManager.getDefaultBackend();
        const user = req.user;
        
        // Verify ownership
        const containers = await backend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = verifyContainerOwnership(container, user);
        
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
        const backend = backendManager.getDefaultBackend();
        const user = req.user;
        
        // Check cache first
        const cachedStats = await cacheManager.getCachedContainerStats(req.params.id);
        if (cachedStats && user.role !== 'admin') { // Admins always get fresh stats
            return res.json({stats: cachedStats});
        }
        
        // Verify ownership
        const containers = await backend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = verifyContainerOwnership(container, user);
        
        if (!isOwner && user.role !== 'admin') {
            return res.status(403).json({error: "Access denied"});
        }
        
        const stats = await lxcBackend.stats(req.params.id);
        
        // Cache stats for 30 seconds
        await cacheManager.cacheContainerStats(req.params.id, stats);
        
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
        const backend = backendManager.getDefaultBackend();
        const user = req.user;
        
        // Verify ownership
        const containers = await backend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = verifyContainerOwnership(container, user);
        
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
        const backend = backendManager.getDefaultBackend();
        const user = req.user;
        
        // Verify ownership
        const containers = await backend.list();
        const container = containers.find(c => c.Id.startsWith(req.params.id));
        
        if (!container) {
            return res.status(404).json({error: "Container not found"});
        }
        
        const labels = container.Labels || {};
        const isOwner = verifyContainerOwnership(container, user);
        
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
        // Legacy authentication removed - use proper JWT/API key authentication
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
        const backend = backendManager.getDefaultBackend();
        
        // Verify container ownership
        const containers = await backend.list();
        const container = containers.find(c => c.Id.startsWith(containerId));
        
        if (!container) {
            ws.send('Container not found');
            ws.close();
            return;
        }
        
        const labels = container.Labels || {};
        const isOwner = verifyContainerOwnership(container, user);
        
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

// Global error handler (must be last middleware)
app.use(errorHandler);

// Graceful shutdown
process.on('SIGTERM', () => {
    console.log('Shutting down...');
    server.close(() => {
        db.close();
        process.exit(0);
    });
});