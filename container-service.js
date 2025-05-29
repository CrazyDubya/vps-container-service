const express = require("express");
const crypto = require("crypto");
const http = require("http");
require('./lib/database'); // Initialize database and tables on startup
const WebSocket = require("ws");
const cors = require("cors");
const multer = require("multer");
const fs = require("fs");
const os = require("os"); // Added for os.tmpdir()
const path = require("path");
const tar = require('tar-stream');
const Docker = require('dockerode');
const validator = require('validator');
const BackendFactory = require("./lib/backend-factory");
const OperationalError = require('./lib/operational-error'); // Use external OperationalError
const authRoutes = require('./routes/auth-routes'); // Auth routes
const containerExtrasRoutes = require('./routes/container-extras-routes'); // Container Extras Routes
const { authenticateJWT } = require('./middleware/auth-middleware'); // JWT Auth middleware
const { authenticateCloudflareJWT } = require('./middleware/cloudflare-auth-middleware'); // Cloudflare JWT Auth
const { authorizeContainerAccess } = require('./middleware/container-auth-middleware'); // Container Auth middleware

// Input Validation Helper Functions
const isValidImageName = (name) => {
  if (typeof name !== 'string' || name.length === 0 || name.length > 255) return false;
  // Allows alphanumeric, slashes, colons, hyphens, periods.
  // Official regex is complex, this is a simplified one for common valid names.
  // docker/distribution/reference/regexp.go
  return /^[a-zA-Z0-9_.-]+([\/][a-zA-Z0-9_.-]+)*(:[a-zA-Z0-9_.-]+)?$/.test(name);
};

const isValidContainerNameChars = (name) => {
  if (typeof name !== 'string' || name.length === 0 || name.length > 63) return false;
  // Docker: /^[a-zA-Z0-9][a-zA-Z0-9_.-]+$/
  // LXC (from previous subtask, more strict): /^[a-zA-Z0-9-]+$/, no leading/trailing/consecutive hyphens
  // Let's use a general one that is safe for both and for "cf-" prefixing.
  // For `cf-${name}`, the name itself should be more constrained.
  return /^[a-zA-Z0-9_.-]+$/.test(name) && !name.startsWith('-') && !name.endsWith('-');
};

const isValidLxcIdForService = (id) => { // Used for req.params.id which might be a full cf- prefixed name
    if (typeof id !== 'string') return false;
    if (id.length < 3 || id.length > 63) return false;
    if (!/^cf-[a-zA-Z0-9_.-]+$/.test(id) && !/^[a-zA-Z0-9][a-zA-Z0-9_.-]+$/.test(id) && !/^[a-f0-9]{64}$/.test(id) && !/^[a-f0-9]{12,64}$/.test(id) ) {
        // Allow cf-prefixed, docker default names (word_word), or docker IDs (hex)
        // This regex is a bit permissive for general IDs but covers common cases seen in the app
        // A truly robust solution might need context (is this a docker hash, a cf- name, etc.)
        // For now, focusing on character safety.
        if (!/^[a-zA-Z0-9_.-]+$/.test(id.replace(/^cf-/, ''))) return false;
    }
    if (id.includes('..')) return false; // No path traversal attempts in IDs
    return true;
};


const isValidEnvVar = (envString) => {
  if (typeof envString !== 'string') return false;
  const parts = envString.split('=');
  if (parts.length < 2) return false; // Must have at least one '='
  const varName = parts[0];
  const varValue = parts.slice(1).join('='); // Handle cases where value contains '='
  if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(varName)) return false; // Standard env var name
  // Value can be more flexible, but disallow obvious problematic chars like null bytes or too long
  if (varValue.includes('\0') || varValue.length > 4096) return false;
  return true;
};

const isSafePath = (filePath) => {
  if (typeof filePath !== 'string' || filePath.length === 0 || filePath.length > 1024) return false;
  if (filePath.includes('\0')) return false; // No null bytes
  if (filePath.includes('..')) return false; // No directory traversal
  // Path should ideally be relative, or absolute but well-formed.
  // For putArchive, Docker expects path relative to container root or absolute.
  // For getArchive, it's similar.
  // This check is basic; context of use matters.
  // Ensure it doesn't start with weird things if it's meant to be relative.
  if (filePath.startsWith('/') || /^[a-zA-Z]:\\/.test(filePath)) { // Absolute path
    return validator.isWhitelisted(filePath.replace(/\//g, ''), 'a-zA-Z0-9_.-'); // Check components
  }
  // For relative paths, check components
  const parts = filePath.split('/');
  return parts.every(part => validator.isWhitelisted(part, 'a-zA-Z0-9_.-') || part === '');
};

const isSafeFileName = (fileName) => {
  if (typeof fileName !== 'string' || fileName.length === 0 || fileName.length > 255) return false;
  if (fileName.includes('\0') || fileName.includes('/') || fileName.includes('\\')) return false;
  // Basic check for common safe filename characters (alphanumeric, dots, hyphens, underscores)
  return /^[a-zA-Z0-9_.-]+$/.test(fileName);
};


const app = express();
const server = http.createServer(app);

app.use(express.json());
app.use(cors());

const API_KEY = process.env.API_KEY;
const JWT_SECRET = process.env.JWT_SECRET;
const CLOUDFLARE_TEAM_DOMAIN = process.env.CLOUDFLARE_TEAM_DOMAIN;
const CLOUDFLARE_AUDIENCE_TAG = process.env.CLOUDFLARE_AUDIENCE_TAG;

// Crypto Mining Prevention Settings
const DEFAULT_CRYPTO_ENV_PATTERNS = "WALLET_ADDRESS=.*,POOL_URL=.*,STRATUM_URL=.*,XMRIG_.*,MINER_.*,MONERO=.*";
const CRYPTO_SUSPICIOUS_ENV_PATTERNS_RAW = process.env.CRYPTO_SUSPICIOUS_ENV_PATTERNS || DEFAULT_CRYPTO_ENV_PATTERNS;
let CRYPTO_SUSPICIOUS_ENV_PATTERNS_REGEXPS = [];
if (CRYPTO_SUSPICIOUS_ENV_PATTERNS_RAW) {
    CRYPTO_SUSPICIOUS_ENV_PATTERNS_REGEXPS = CRYPTO_SUSPICIOUS_ENV_PATTERNS_RAW.split(',')
        .map(p => p.trim())
        .filter(p => p.length > 0)
        .map(pattern => {
            try {
                return new RegExp(pattern, 'i'); // Case-insensitive
            } catch (e) {
                console.error(`Invalid regex pattern in CRYPTO_SUSPICIOUS_ENV_PATTERNS: "${pattern}". Error: ${e.message}. This pattern will be ignored.`);
                return null;
            }
        })
        .filter(regex => regex !== null);
}

const CRYPTO_REJECT_ON_SUSPICIOUS_ENV_BOOL = (process.env.CRYPTO_REJECT_ON_SUSPICIOUS_ENV || "false").toLowerCase() === 'true';

const DEFAULT_CRYPTO_PROCESS_NAMES = "xmrig,nbminer,t-rex,stratum,minerd,cpuminer,ccminer,ethminer,claymore";
const CRYPTO_SUSPICIOUS_PROCESS_NAMES_RAW = process.env.CRYPTO_SUSPICIOUS_PROCESS_NAMES || DEFAULT_CRYPTO_PROCESS_NAMES;
const CRYPTO_SUSPICIOUS_PROCESS_NAMES_ARRAY = CRYPTO_SUSPICIOUS_PROCESS_NAMES_RAW.split(',')
    .map(p => p.trim().toLowerCase())
    .filter(p => p.length > 0);

if (!API_KEY) {
    console.error("CRITICAL: API_KEY environment variable is not set. Service cannot start.");
    process.exit(1);
}

if (!JWT_SECRET) {
    console.error("CRITICAL: JWT_SECRET environment variable is not set. Service cannot start.");
    process.exit(1);
}

if (!CLOUDFLARE_TEAM_DOMAIN || !CLOUDFLARE_AUDIENCE_TAG) {
    console.warn("WARNING: CLOUDFLARE_TEAM_DOMAIN or CLOUDFLARE_AUDIENCE_TAG is not set. Cloudflare Access authentication will be disabled.");
} else {
    console.log(`INFO: Cloudflare Access authentication enabled for team domain: ${CLOUDFLARE_TEAM_DOMAIN} and audience: ${CLOUDFLARE_AUDIENCE_TAG}`);
}

console.log("INFO: Crypto-Mining Prevention Settings:");
console.log(`  Suspicious ENV Patterns (raw): "${CRYPTO_SUSPICIOUS_ENV_PATTERNS_RAW}"`);
console.log(`  Compiled ENV Patterns Count: ${CRYPTO_SUSPICIOUS_ENV_PATTERNS_REGEXPS.length}`);
console.log(`  Reject on ENV Match: ${CRYPTO_REJECT_ON_SUSPICIOUS_ENV_BOOL}`);
console.log(`  Suspicious Process Names: "${CRYPTO_SUSPICIOUS_PROCESS_NAMES_ARRAY.join(', ')}"`);


// WebSocket server for interactive terminals
const wss = new WebSocket.Server({ 
    server, 
    path: '/terminal'
});

// Active terminal sessions
const terminalSessions = new Map();

wss.on('connection', (ws, req) => {
    const url = new URL(req.url, `http://${req.headers.host}`);
    const containerId = url.searchParams.get('container');
    const apiKey = req.headers['sec-websocket-protocol'];
    const backendTypeParam = url.searchParams.get('backendType'); // Read backendType
    
    // Authenticate WebSocket connection
    if (apiKey !== API_KEY) {
        console.log('WebSocket authentication failed: Invalid API key provided via Sec-WebSocket-Protocol header.');
        ws.close(1008, 'Unauthorized');
        return;
    }
    
    if (!containerId) {
        ws.close(1008, 'Container ID required');
        return;
    }
    
    console.log(`Terminal session started for container: ${containerId} (authenticated via Sec-WebSocket-Protocol)`);
    
    // Create terminal session
    let terminalProcess = null; // This will hold the object with { writeData, resize, kill } or { stream, exec }
    
    const startTerminal = async () => {
        try {
            let backend;
            let detectedBackendType = 'docker'; // Default to docker

            if (backendTypeParam) {
                try {
                    backend = BackendFactory.create(backendTypeParam);
                    await backend.getInfo(containerId); // Verify container exists with this backend
                    detectedBackendType = backendTypeParam;
                } catch (e) {
                    ws.send(`Error: Specified backendType "${backendTypeParam}" failed to load container or container not found.\r\n`);
                    ws.close();
                    return;
                }
            } else {
                // Auto-detect backend if not specified
                try {
                    backend = BackendFactory.create('docker');
                    await backend.getInfo(containerId);
                    detectedBackendType = 'docker';
                } catch (dockerError) {
                    try {
                        backend = BackendFactory.create('lxc');
                        await backend.getInfo(containerId);
                        detectedBackendType = 'lxc';
                    } catch (lxcError) {
                        throw new Error(`Container ${containerId} not found in any backend`);
                    }
                }
            }
            
            console.log(`Attempting to start terminal for container ${containerId} using ${detectedBackendType} backend.`);

            if (detectedBackendType === 'docker') {
                const docker = new Docker(); // Ensure dockerode is instanced if using docker
                const container = docker.getContainer(containerId);
                
                const exec = await container.exec({
                    Cmd: ['/bin/sh'], AttachStdin: true, AttachStdout: true, AttachStderr: true, Tty: true
                });
                
                const stream = await exec.start({ hijack: true, stdin: true });
                
                terminalProcess = { processInterface: stream, type: 'docker', dockerExec: exec }; // Save the exec for later inspection if needed
                
                ws.on('message', (data) => {
                    if (terminalProcess && terminalProcess.processInterface) {
                        terminalProcess.processInterface.write(data);
                    }
                });
                
                stream.on('data', (data) => {
                    if (ws.readyState === WebSocket.OPEN) { ws.send(data); }
                });
                
                stream.on('end', () => { ws.close(); });
                
            } else if (detectedBackendType === 'lxc') {
                const lxcBackend = BackendFactory.create('lxc'); // Ensure we have an LXC backend instance
                const ptyProcess = await lxcBackend.startTerminal(
                    containerId,
                    (data) => { if (ws.readyState === WebSocket.OPEN) { ws.send(data); } },
                    ({ exitCode, signal, error }) => {
                        console.log(`LXC terminal for ${containerId} closed. Exit code: ${exitCode}, signal: ${signal}, error: ${error ? error.message : 'none'}`);
                        ws.close();
                    }
                    // Default rows/cols will be used from lxc-backend.js
                );
                terminalProcess = { processInterface: ptyProcess, type: 'lxc' };

                ws.on('message', (data) => {
                    if (terminalProcess && terminalProcess.processInterface) {
                        try {
                            // Attempt to parse for resize commands
                            const messageString = data.toString();
                            const msg = JSON.parse(messageString);
                            if (msg.type === 'resize' && typeof msg.cols === 'number' && typeof msg.rows === 'number') {
                                terminalProcess.processInterface.resize(msg.cols, msg.rows);
                            } else {
                                // If not a resize command, send as is (e.g. user input)
                                terminalProcess.processInterface.writeData(messageString);
                            }
                        } catch (e) {
                            // Not a JSON message, assume it's direct input for the terminal
                            terminalProcess.processInterface.writeData(data);
                        }
                    }
                });
            } else {
                throw new Error(`Unsupported backend type: ${detectedBackendType}`);
            }
        } catch (error) {
            console.error(`Terminal setup error for container ${containerId}:`, error);
            ws.send(`Error: ${error.message}\r\n`);
            ws.close();
        }
    };
    
    startTerminal();
    
    ws.on('close', () => {
        console.log(`Terminal session closed for container: ${containerId}`);
        if (terminalProcess) {
            if (terminalProcess.type === 'docker' && terminalProcess.processInterface) {
                // For Docker, the stream itself is the main interface to end.
                // Inspecting exec might be needed if direct kill is required.
                // terminalProcess.dockerExec.inspect(...); // To see if it's running
                terminalProcess.processInterface.end(); 
            } else if (terminalProcess.type === 'lxc' && terminalProcess.processInterface) {
                terminalProcess.processInterface.kill();
            }
        }
        terminalSessions.delete(containerId);
    });
    
    ws.on('error', (error) => {
        console.error(`WebSocket error for container ${containerId}:`, error);
        if (terminalProcess) {
             if (terminalProcess.type === 'docker' && terminalProcess.processInterface) {
                terminalProcess.processInterface.end();
            } else if (terminalProcess.type === 'lxc' && terminalProcess.processInterface) {
                terminalProcess.processInterface.kill();
            }
        }
         ws.close(); // Ensure WebSocket is closed on error
    });
    
    // Store the ws and terminalProcess for the session
    // This will be overwritten if startTerminal() is called again for the same containerId (e.g. on reconnect)
    // but the old terminalProcess should be cleaned up by its 'close' or 'error' handlers.
    terminalSessions.set(containerId, { ws, getTerminalProcess: () => terminalProcess });
});

app.get("/health", (req, res) => {
    res.json({
        status: "healthy",
        timestamp: new Date().toISOString()
    });
});

// --- Auth Routes ---
app.use('/auth', authRoutes);
app.use('/containers/:id', containerExtrasRoutes); // Mount container-specific extra routes


// --- Application Routes ---
// All /containers/* routes are now protected by JWT (local or Cloudflare)
app.post("/containers/create", authenticateCloudflareJWT, authenticateJWT, async (req, res, next) => {
    try {
        const { image, template, env, name, id: configId, ...restConfig } = req.body;
        let config = { ...restConfig };

        // Validate image name
        if (image && !isValidImageName(image)) {
            return next(new OperationalError('Invalid image name format.', 400));
        }
        config.image = image;

        // Validate template name (if used for Docker, treat as a name component)
        if (template) {
            if (!isValidContainerNameChars(template)) {
                return next(new OperationalError('Invalid template name format.', 400));
            }
            config.template = template;
        }
        
        // Validate environment variables
        if (env) {
            if (!Array.isArray(env) || !env.every(isValidEnvVar)) {
                return next(new OperationalError('Invalid environment variable format. Expected array of "VAR=value".', 400));
            }
            config.env = env;
        }

        // Validate container name (for cf-name)
        if (name && !isValidContainerNameChars(name)) {
            return next(new OperationalError('Invalid container name format in body.name.', 400));
        }
        config.name = name; // Will be prefixed with cf- by backend if used for LXC

        // Validate config.id (if provided, used by backends, e.g. LXC cf-${config.id})
        if (configId && !isValidContainerNameChars(configId)) {
            return next(new OperationalError('Invalid container ID format in body.id.', 400));
        }
        config.id = configId;

        // Crypto-mining prevention: Check environment variables
        if (config.env && CRYPTO_SUSPICIOUS_ENV_PATTERNS_REGEXPS.length > 0) {
            for (const envVar of config.env) { // envVar is like "VAR=value"
                for (const regex of CRYPTO_SUSPICIOUS_ENV_PATTERNS_REGEXPS) {
                    if (regex.test(envVar)) {
                        const logMessage = `Suspicious environment variable found for container creation attempt (user: ${req.user ? req.user.username : 'unknown'}, name: ${config.name || config.id || 'N/A'}): "${envVar}" matching pattern "${regex.source}"`;
                        console.warn(logMessage);
                        if (CRYPTO_REJECT_ON_SUSPICIOUS_ENV_BOOL) {
                            return next(new OperationalError(`Container creation rejected due to suspicious environment variable: ${envVar.split('=')[0]}`, 400));
                        }
                        // If not rejecting, just log and continue
                        break; // Found a match for this envVar, no need to check other patterns for it
                    }
                }
            }
        }

        // Handle template vs image parameter compatibility (logic from original code)
        if (config.template && !config.image) {
            const templateMap = {
                'ubuntu': 'ubuntu:latest',
                'alpine': 'alpine:latest',
                'python': 'python:3.9-alpine',
                'nodejs': 'node:18-alpine',
                'node': 'node:18-alpine',
                'nginx': 'nginx:alpine'
            };
            config.image = templateMap[config.template] || config.template;
        }
        
        // Handle memory vs maxMemory parameter compatibility
        if (config.memory && !config.maxMemory) {
            // Convert memory format like "128m" to number
            const memoryStr = config.memory.toString().toLowerCase();
            if (memoryStr.endsWith('m')) {
                config.maxMemory = parseInt(memoryStr.slice(0, -1));
            } else {
                config.maxMemory = parseInt(memoryStr) || 256;
            }
        }
        
        // Set defaults
        if (!config.image) {
            return next(new OperationalError('Image or template required', 400));
        }
        if (!config.maxMemory) {
            config.maxMemory = 256;
        }
        
        // Determine backend based on requirements
        const backendType = config.backendType || BackendFactory.autoSelectBackend(config);
        const backend = BackendFactory.create(backendType);
        
        // Add userId to the config for backend.create()
        if (req.user && req.user.userId) {
            config.userId = req.user.userId;
        } else {
            // This should not happen if authenticateJWT is working correctly
            return next(new OperationalError('User ID not found in token payload.', 500));
        }
        
        const containerId = await backend.create(config);
        const info = await backend.getInfo(containerId);
        
        res.json({
            id: containerId,
            name: info.name,
            status: info.status,
            backend: backendType,
            ports: info.ports || {}
        });
    } catch (error) {
        next(error); // Pass to centralized error handler
    }
});

// Execute command in container
app.post('/containers/:id/exec', authenticateCloudflareJWT, authenticateJWT, authorizeContainerAccess, async (req, res, next) => {
  try {
    const containerId = req.params.id;
    if (!isValidLxcIdForService(containerId)) { // Using broader validator for existing IDs
        return next(new OperationalError('Invalid container ID format in URL parameter.', 400));
    }

    const { command, backendType } = req.body;
    if (typeof command !== 'string' || command.trim() === '') {
        return next(new OperationalError('Command must be a non-empty string.', 400));
    }
    
    // Auto-detect backend if not specified
    let backend;
    if (backendType) {
      backend = BackendFactory.create(backendType);
    } else {
      // Try Docker first, then LXC
      try {
        backend = BackendFactory.create('docker');
        await backend.getInfo(containerId);
      } catch (dockerError) {
        try {
          backend = BackendFactory.create('lxc');
          await backend.getInfo(containerId);
        } catch (lxcError) {
          throw new Error(`Container ${containerId} not found in any backend`);
        }
      }
    }
    
    const result = await backend.exec(containerId, command);
    res.json(result);
  } catch (error) {
    next(error); // Pass to centralized error handler
  }
});

// List containers
app.get('/containers', authenticateCloudflareJWT, authenticateJWT, async (req, res, next) => {
  try {
    const dockerBackend = BackendFactory.create('docker');
    const lxcBackend = BackendFactory.create('lxc');
    
    let userIdToFilter = null;
    if (req.user && req.user.role === 'user' && req.user.userId) {
      userIdToFilter = req.user.userId;
    } 
    // Admins (req.user.role === 'admin') will have userIdToFilter = null, so they see all containers.
    // If req.user is not defined (e.g. if JWT was optional for some reason), it also sees all.

    const [dockerContainers, lxcContainers] = await Promise.allSettled([
      dockerBackend.list(userIdToFilter),
      lxcBackend.list(userIdToFilter)
    ]);
    
    const containers = [
      ...(dockerContainers.status === 'fulfilled' ? dockerContainers.value : []),
      ...(lxcContainers.status === 'fulfilled' ? lxcContainers.value : [])
    ];
    
    res.json({ containers });
  } catch (error) {
    next(error); // Pass to centralized error handler
  }
});

// Get container info
app.get('/containers/:id', authenticateCloudflareJWT, authenticateJWT, authorizeContainerAccess, async (req, res, next) => {
  try {
    const containerId = req.params.id;
    if (!isValidLxcIdForService(containerId)) {
        return next(new OperationalError('Invalid container ID format in URL parameter.', 400));
    }
    const { backendType } = req.query;
    
    let backend;
    if (backendType) {
      backend = BackendFactory.create(backendType);
    } else {
      // Auto-detect backend
      try {
        backend = BackendFactory.create('docker');
        await backend.getInfo(containerId);
      } catch (dockerError) {
        backend = BackendFactory.create('lxc');
      }
    }
    
    const info = await backend.getInfo(containerId);
    res.json({ ...info, backend: backend.getBackendType() });
  } catch (error) {
    next(error); // Pass to centralized error handler
  }
});

// Stop container
app.post('/containers/:id/stop', authenticateCloudflareJWT, authenticateJWT, authorizeContainerAccess, async (req, res, next) => {
  try {
    const containerId = req.params.id;
    if (!isValidLxcIdForService(containerId)) {
        return next(new OperationalError('Invalid container ID format in URL parameter.', 400));
    }
    const { backendType } = req.body;
    
    let backend;
    if (backendType) {
      backend = BackendFactory.create(backendType);
    } else {
      // Auto-detect backend
      try {
        backend = BackendFactory.create('docker');
        await backend.getInfo(containerId);
      } catch (dockerError) {
        backend = BackendFactory.create('lxc');
      }
    }
    
    await backend.stop(containerId);
    res.json({ message: 'Container stopped successfully' });
  } catch (error) {
    next(error); // Pass to centralized error handler
  }
});

// Remove container
app.delete('/containers/:id', authenticateCloudflareJWT, authenticateJWT, authorizeContainerAccess, async (req, res, next) => {
  try {
    const containerId = req.params.id;
    if (!isValidLxcIdForService(containerId)) {
        return next(new OperationalError('Invalid container ID format in URL parameter.', 400));
    }
    const { backendType } = req.body;
    
    let backend;
    if (backendType) {
      backend = BackendFactory.create(backendType);
    } else {
      // Auto-detect backend
      try {
        backend = BackendFactory.create('docker');
        await backend.getInfo(containerId);
      } catch (dockerError) {
        backend = BackendFactory.create('lxc');
      }
    }
    
    await backend.remove(containerId);
    res.json({ message: 'Container removed successfully' });
  } catch (error) {
    next(error); // Pass to centralized error handler
  }
});

// Get container logs
app.get('/containers/:id/logs', authenticateCloudflareJWT, authenticateJWT, authorizeContainerAccess, async (req, res, next) => {
  try {
    const containerId = req.params.id;
    if (!isValidLxcIdForService(containerId)) {
        return next(new OperationalError('Invalid container ID format in URL parameter.', 400));
    }
    const { backendType, lines = 100 } = req.query;
     if (lines && !validator.isInt(lines.toString(), { min: 1, max: 1000 })) {
        return next(new OperationalError('Invalid lines parameter. Must be an integer between 1 and 1000.', 400));
    }
    
    let backend;
    if (backendType) {
      backend = BackendFactory.create(backendType);
    } else {
      // Auto-detect backend
      try {
        backend = BackendFactory.create('docker');
        await backend.getInfo(containerId);
      } catch (dockerError) {
        backend = BackendFactory.create('lxc');
      }
    }
    
    const logs = await backend.getLogs(containerId, parseInt(lines));
    res.json({ logs });
  } catch (error) {
    next(error); // Pass to centralized error handler
  }
});

// File upload/download setup
const upload = multer({
  storage: multer.diskStorage({
    destination: function (req, file, cb) {
      const uploadPath = path.join(os.tmpdir(), 'cf-uploads');
      fs.mkdir(uploadPath, { recursive: true }, (err) => { // Use fs.mkdir for async creation
        if (err) {
          console.error("Failed to create upload directory:", err);
          return cb(err);
        }
        cb(null, uploadPath);
      });
    },
    filename: function (req, file, cb) {
      // More unique filename
      const uniqueSuffix = Date.now() + '-' + crypto.randomBytes(6).toString('hex');
      cb(null, uniqueSuffix + '-' + file.originalname.replace(/[^a-zA-Z0-9_.-]/g, '_')); // Sanitize originalname
    }
  }),
  limits: { 
    fileSize: 10 * 1024 * 1024 // 10MB limit
  }
});

// Upload file to container
app.post('/containers/:id/files', authenticateCloudflareJWT, authenticateJWT, authorizeContainerAccess, upload.single('file'), async (req, res, next) => {
  let tempFilePath = null; // Keep track of the temp file path for cleanup
  try {
    if (req.file && req.file.path) {
      tempFilePath = req.file.path;
    }

    const containerId = req.params.id;
    if (!isValidLxcIdForService(containerId)) {
        return next(new OperationalError('Invalid container ID format in URL parameter.', 400));
    }

    const { path: targetPath = '/tmp' } = req.body;
    if (!isSafePath(targetPath)) {
        return next(new OperationalError('Invalid target path format.', 400));
    }

    const file = req.file;
    if (!file) {
      return next(new OperationalError('No file provided', 400));
    }
    if (!isSafeFileName(file.originalname)) {
        return next(new OperationalError('Invalid file name.', 400));
    }
    
    // Auto-detect backend
    let backend;
    try {
      backend = BackendFactory.create('docker');
      await backend.getInfo(containerId);
    } catch (dockerError) {
      backend = BackendFactory.create('lxc');
    }
    
    if (backend.getBackendType() === 'docker') {
      const docker = new Docker();
      const container = docker.getContainer(containerId);
      
      const pack = tar.pack();
      const fileStream = fs.createReadStream(req.file.path);
      
      // Create a promise to handle stream completion for tar packing
      const packPromise = new Promise((resolve, reject) => {
        const entry = pack.entry({ name: file.originalname, size: req.file.size }, (err) => {
          if (err) return reject(err);
        });
        
        fileStream.pipe(entry)
          .on('finish', () => {
            pack.finalize(); // Finalize the tar pack once the file stream is done
            resolve();
          })
          .on('error', (err) => {
            pack.destroy(err); // Destroy pack stream on file stream error
            reject(err);
          });
      });

      await packPromise; // Wait for the file to be fully piped into the tar stream and pack finalized
      
      await container.putArchive(pack, { path: targetPath });
      
      res.json({ 
        message: 'File uploaded successfully using dockerode and disk storage',
        path: `${targetPath}/${file.originalname}`,
        size: file.size
      });
    } else { // Assuming LXC backend
      const lxcBackend = backend; // Already created as 'lxc'
      const fileReadStream = fs.createReadStream(req.file.path);
      
      // Ensure targetPath is absolute. If not, default to /tmp.
      // req.body.path (targetPath) is validated by isSafePath, which allows relative.
      // For inside container, we need absolute.
      let containerSideTargetPathDir = targetPath;
      if (!containerSideTargetPathDir.startsWith('/')) {
          console.warn(`Provided targetPath '${targetPath}' is not absolute. Defaulting to /tmp for LXC file push.`);
          containerSideTargetPathDir = '/tmp';
      }
      // isSafeFileName already validated file.originalname
      const targetPathInContainer = path.join(containerSideTargetPathDir, file.originalname);

      await lxcBackend.pushFile(containerId, targetPathInContainer, fileReadStream);
      res.json({
        message: 'File uploaded successfully to LXC container',
        path: targetPathInContainer,
        size: file.size
      });
    }
  } catch (error) {
    next(error); // Pass to centralized error handler
  } finally {
    if (tempFilePath) {
      fs.unlink(tempFilePath, (unlinkErr) => {
        if (unlinkErr) {
          console.error(`Failed to delete temporary file: ${tempFilePath}`, unlinkErr);
        } else {
          console.log(`Successfully deleted temporary file: ${tempFilePath}`);
        }
      });
    }
  }
});

// Download file from container
app.get('/containers/:id/files/*', authenticateCloudflareJWT, authenticateJWT, authorizeContainerAccess, async (req, res, next) => {
  try {
    const containerId = req.params.id;
     if (!isValidLxcIdForService(containerId)) {
        return next(new OperationalError('Invalid container ID format in URL parameter.', 400));
    }

    const filePath = '/' + req.params[0];
    if (!isSafePath(filePath)) { // Ensure filePath is validated as a path
        return next(new OperationalError('Invalid file path format.', 400));
    }
    
    // Auto-detect backend
    let backend;
    try {
      backend = BackendFactory.create('docker');
      await backend.getInfo(containerId);
    } catch (dockerError) {
      backend = BackendFactory.create('lxc');
    }
    
    if (backend.getBackendType() === 'docker') {
      const docker = new Docker();
      const container = docker.getContainer(containerId);
      
      const stream = await container.getArchive({ path: filePath });
      const extract = tar.extract();

      let fileBuffer;
      let fileName;

      extract.on('entry', (header, entryStream, next) => {
        fileName = header.name;
        const chunks = [];
        entryStream.on('data', (chunk) => chunks.push(chunk));
        entryStream.on('end', () => {
          fileBuffer = Buffer.concat(chunks);
          next();
        });
        entryStream.resume();
      });

      extract.on('finish', () => {
        if (!fileBuffer) {
          return next(new OperationalError('File not found in archive or archive is empty', 404));
        }
        res.setHeader('Content-Disposition', `attachment; filename="${path.basename(fileName || filePath)}"`);
        res.setHeader('Content-Type', 'application/octet-stream');
        res.send(fileBuffer);
      });
      
      stream.pipe(extract).on('error', (err) => {
        console.error('Error extracting file from archive:', err);
        // Check if the error indicates file not found
        if (err.statusCode === 404 || (err.json && err.json.message && err.json.message.toLowerCase().includes('no such file or directory'))) {
            return next(new OperationalError(`File not found: ${filePath}`, 404));
        }
        // For other errors from stream.pipe, pass them to the central error handler
        return next(new OperationalError(`Failed to get file from container: ${err.message}`, 500));
      });

    } else { // Assuming LXC backend
      const lxcBackend = backend; // Already created as 'lxc'
      // filePath is already validated as an absolute path by isSafePath
      const fileStream = await lxcBackend.pullFile(containerId, filePath);

      res.setHeader('Content-Disposition', `attachment; filename="${path.basename(filePath)}"`);
      res.setHeader('Content-Type', 'application/octet-stream');

      fileStream.pipe(res)
        .on('error', (streamErr) => {
          console.error('LXC pullFile stream error:', streamErr);
          // Check if headers already sent. If so, can't send a new status.
          if (!res.headersSent) {
            // If error message indicates file not found (this depends on lxc-backend's error messages)
            if (streamErr.message.toLowerCase().includes('no such file or directory') || streamErr.message.toLowerCase().includes('cat: can\'t open')) {
              return next(new OperationalError(`File not found in LXC container: ${filePath}`, 404));
            }
            return next(new OperationalError(`Error streaming file from LXC container: ${streamErr.message}`, 500));
          } else {
            // If headers sent, destroy the stream and hope client notices
             res.end();
          }
        })
        .on('finish', () => {
            // Stream finished successfully
        });
    }
  } catch (error) {
    next(error); // Pass to centralized error handler
  }
});

// Get container stats
app.get('/containers/:id/stats', authenticateCloudflareJWT, authenticateJWT, authorizeContainerAccess, async (req, res, next) => {
  try {
    const containerId = req.params.id;
    if (!isValidLxcIdForService(containerId)) {
        return next(new OperationalError('Invalid container ID format in URL parameter.', 400));
    }
    
    // Auto-detect backend
    let backend;
    try {
      backend = BackendFactory.create('docker');
      await backend.getInfo(containerId);
    } catch (dockerError) {
      backend = BackendFactory.create('lxc');
    }
    
    if (backend.getBackendType() === 'docker') {
      const docker = new Docker();
      const container = docker.getContainer(containerId);
      
      const statsStream = await container.stats({ stream: true });
      
      statsStream.on('data', (chunk) => {
        statsStream.destroy(); // Stop the stream after receiving the first stats object
        
        const stats = JSON.parse(chunk.toString());
        
        // Calculate CPU percentage
        let cpuPercent = "0.00%";
        const cpuDelta = stats.cpu_stats.cpu_usage.total_usage - (stats.precpu_stats.cpu_usage ? stats.precpu_stats.cpu_usage.total_usage : 0);
        const systemDelta = stats.cpu_stats.system_cpu_usage - (stats.precpu_stats.system_cpu_usage ? stats.precpu_stats.system_cpu_usage : 0);
        const cpuCores = stats.cpu_stats.online_cpus || stats.cpu_stats.cpu_usage.percpu_usage.length;

        if (systemDelta > 0 && cpuDelta > 0 && cpuCores > 0) {
          cpuPercent = ((cpuDelta / systemDelta) * cpuCores * 100.0).toFixed(2) + "%";
        }

        // Memory usage and percentage
        const memUsage = (stats.memory_stats.usage - (stats.memory_stats.stats && stats.memory_stats.stats.inactive_file ? stats.memory_stats.stats.inactive_file : 0)); // more accurate usage
        const memLimit = stats.memory_stats.limit;
        const memPercent = memLimit > 0 ? ((memUsage / memLimit) * 100.0).toFixed(2) + "%" : "0.00%";

        // Network I/O
        let netRx = 0, netTx = 0;
        if (stats.networks) {
          for (const netInterface in stats.networks) {
            netRx += stats.networks[netInterface].rx_bytes;
            netTx += stats.networks[netInterface].tx_bytes;
          }
        }
        const netIO = `${(netRx / (1024*1024)).toFixed(2)}MB / ${(netTx / (1024*1024)).toFixed(2)}MB`;

        // Block I/O (Disk)
        let blockRead = 0, blockWrite = 0;
        if (stats.blkio_stats && stats.blkio_stats.io_service_bytes_recursive) {
            stats.blkio_stats.io_service_bytes_recursive.forEach(entry => {
                if (entry.op === 'Read') blockRead += entry.value;
                if (entry.op === 'Write') blockWrite += entry.value;
            });
        }
        const blockIO = `${(blockRead / (1024*1024)).toFixed(2)}MB / ${(blockWrite / (1024*1024)).toFixed(2)}MB`;

        res.json({
          cpu: cpuPercent,
          memory: {
            usage: `${(memUsage / (1024*1024)).toFixed(2)}MB`,
            percent: memPercent
          },
          network: netIO,
          disk: blockIO,
          timestamp: stats.read ? new Date(stats.read).toISOString() : new Date().toISOString()
        });
      });

      statsStream.on('error', (err) => {
        console.error('Error getting container stats via stream:', err);
        if (!res.headersSent) {
            // Pass the error to the centralized handler
            return next(new OperationalError(`Failed to get container stats: ${err.message}`, 500));
        }
      });
       statsStream.on('end', () => {
        if (!res.headersSent) {
             // This might happen if the stream ends before data is sent (e.g. container stopped)
            console.log('Stats stream ended before data was sent for container:', containerId);
            // Pass as an operational error to the centralized handler
            return next(new OperationalError('Container stats stream ended unexpectedly. The container might have stopped.', 404));
        }
      });

    } else { // Assuming LXC backend
      const lxcBackend = backend; // Already created as 'lxc'
      const statsData = await lxcBackend.getStats(containerId);

      let memoryUsageMiB = "N/A";
      if (statsData.memoryUsageBytes !== null && !isNaN(statsData.memoryUsageBytes)) {
        memoryUsageMiB = (statsData.memoryUsageBytes / (1024 * 1024)).toFixed(2) + "MiB";
      }

      let memoryPercent = "N/A";
      if (statsData.memoryUsageBytes !== null && !isNaN(statsData.memoryUsageBytes) &&
          statsData.memoryLimitBytes !== null && !isNaN(statsData.memoryLimitBytes) && statsData.memoryLimitBytes > 0) {
        memoryPercent = ((statsData.memoryUsageBytes / statsData.memoryLimitBytes) * 100).toFixed(2) + "%";
      }

      res.json({
        cpu: `CPU Time: ${statsData.cpuRaw}`, // LXC CPU is cumulative time
        memory: {
          usage: memoryUsageMiB,
          percent: memoryPercent
        },
        network: statsData.networkIORaw, // Should be "N/A" as per lxc-backend
        disk: statsData.diskIORaw,
        timestamp: new Date().toISOString()
      });
    }
  } catch (error) {
    next(error); // Pass to centralized error handler
  }
});

// Centralized error handler
app.use((err, req, res, next) => {
  // Log the full error internally for debugging
  // In a production app, you'd use a robust logger like Winston or Pino
  console.error('Error caught by centralized handler:', {
    message: err.message,
    statusCode: err.statusCode,
    isOperational: err.isOperational,
    stack: err.stack,
    // Optionally log req details if helpful, but be careful with sensitive info
    // path: req.path, 
    // method: req.method
  });

  if (err instanceof OperationalError || err.isOperational) {
    return res.status(err.statusCode || 500).json({ error: err.message });
  }

  // For unhandled/unexpected errors, send a generic message
  return res.status(500).json({ error: "An unexpected internal server error occurred." });
});


const PORT = process.env.PORT || 8082;
server.listen(PORT, () => {
    console.log(`Container service running on port ${PORT}`);
    console.log(`WebSocket terminal available at ws://localhost:${PORT}/terminal`);
});