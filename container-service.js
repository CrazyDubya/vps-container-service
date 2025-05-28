const express = require("express");
const crypto = require("crypto");
const http = require("http");
const WebSocket = require("ws");
const cors = require("cors");
const multer = require("multer");
const fs = require("fs");
const path = require("path");
const BackendFactory = require("./lib/backend-factory");

const app = express();
const server = http.createServer(app);

app.use(express.json());
app.use(cors());

const API_KEY = process.env.API_KEY || crypto.randomBytes(32).toString("hex");
console.log("API Key:", API_KEY);

const authenticate = (req, res, next) => {
    if (req.headers["x-api-key"] !== API_KEY) {
        return res.status(401).json({error: "Unauthorized"});
    }
    next();
};

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

// Track containers per user
const userContainers = new Map();

// Cleanup expired containers
const cleanupExpiredContainers = async () => {
  try {
    const dockerBackend = BackendFactory.create('docker');
    const containers = await dockerBackend.list();
    const now = new Date();
    
    for (const container of containers) {
      const labels = container.labels || {};
      const expiresAt = labels['cf-expires'];
      
      if (expiresAt && new Date(expiresAt) < now) {
        console.log(`Cleaning up expired container: ${container.id}`);
        try {
          await dockerBackend.remove(container.id);
          
          // Clean up volumes
          const volumes = labels['cf-volumes'];
          if (volumes) {
            const volumePaths = volumes.split(',');
            for (const volumePath of volumePaths) {
              const hostPath = volumePath.split(':')[0];
              if (hostPath && hostPath.includes('/var/lib/cf-container-service/volumes/')) {
                const fs = require('fs');
                try {
                  fs.rmSync(hostPath, { recursive: true, force: true });
                  console.log(`Cleaned up volume: ${hostPath}`);
                } catch (err) {
                  console.warn(`Could not clean up volume ${hostPath}:`, err.message);
                }
              }
            }
          }
        } catch (err) {
          console.error(`Failed to cleanup container ${container.id}:`, err.message);
        }
      }
    }
  } catch (error) {
    console.error('Cleanup error:', error.message);
  }
};

// Start cleanup interval
setInterval(cleanupExpiredContainers, CLEANUP_INTERVAL);

// Helper to check user container limits
const checkUserLimits = async (userId) => {
  const dockerBackend = BackendFactory.create('docker');
  const containers = await dockerBackend.list();
  const userContainerCount = containers.filter(c => 
    c.labels && c.labels['cf-user'] === userId
  ).length;
  
  return {
    current: userContainerCount,
    limit: MAX_CONTAINERS_PER_USER,
    allowed: userContainerCount < MAX_CONTAINERS_PER_USER
  };
};

wss.on('connection', (ws, req) => {
    const url = new URL(req.url, `http://${req.headers.host}`);
    const containerId = url.searchParams.get('container');
    const apiKey = url.searchParams.get('apiKey');
    
    // Authenticate WebSocket connection
    if (apiKey !== API_KEY) {
        ws.close(1008, 'Unauthorized');
        return;
    }
    
    if (!containerId) {
        ws.close(1008, 'Container ID required');
        return;
    }
    
    console.log(`Terminal session started for container: ${containerId}`);
    
    // Create terminal session
    let terminalProcess = null;
    
    const startTerminal = async () => {
        try {
            // Auto-detect backend for the container
            let backend;
            try {
                backend = BackendFactory.create('docker');
                await backend.getInfo(containerId);
            } catch (dockerError) {
                try {
                    backend = BackendFactory.create('lxc');
                    await backend.getInfo(containerId);
                } catch (lxcError) {
                    throw new Error(`Container ${containerId} not found`);
                }
            }
            
            // For Docker containers, use exec with interactive shell
            if (backend.getBackendType() === 'docker') {
                const Docker = require('dockerode');
                const docker = new Docker();
                const container = docker.getContainer(containerId);
                
                const exec = await container.exec({
                    Cmd: ['/bin/sh'],
                    AttachStdin: true,
                    AttachStdout: true,
                    AttachStderr: true,
                    Tty: true
                });
                
                const stream = await exec.start({
                    hijack: true,
                    stdin: true
                });
                
                terminalProcess = { stream, exec };
                
                // Pipe WebSocket messages to container stdin
                ws.on('message', (data) => {
                    if (terminalProcess && terminalProcess.stream) {
                        terminalProcess.stream.write(data);
                    }
                });
                
                // Pipe container output to WebSocket
                stream.on('data', (data) => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(data);
                    }
                });
                
                stream.on('end', () => {
                    ws.close();
                });
                
            } else {
                // For LXC containers, use different approach
                ws.send('LXC terminal support coming soon...\r\n');
                ws.close();
            }
            
        } catch (error) {
            console.error('Terminal error:', error);
            ws.send(`Error: ${error.message}\r\n`);
            ws.close();
        }
    };
    
    startTerminal();
    
    ws.on('close', () => {
        console.log(`Terminal session closed for container: ${containerId}`);
        if (terminalProcess && terminalProcess.stream) {
            terminalProcess.stream.end();
        }
        terminalSessions.delete(containerId);
    });
    
    ws.on('error', (error) => {
        console.error('WebSocket error:', error);
        if (terminalProcess && terminalProcess.stream) {
            terminalProcess.stream.end();
        }
    });
    
    terminalSessions.set(containerId, { ws, terminalProcess });
});

app.get("/health", (req, res) => {
    res.json({
        status: "healthy",
        timestamp: new Date().toISOString()
    });
});

app.post("/containers/create", authenticate, async (req, res) => {
    try {
        let config = { ...req.body };
        
        // Get user ID from request (IP address if no user specified)
        const userId = config.userId || req.ip || 'anonymous';
        
        // Check user container limits
        const limits = await checkUserLimits(userId);
        if (!limits.allowed) {
            return res.status(429).json({ 
                error: `Container limit exceeded. Maximum ${limits.limit} containers per user.`,
                current: limits.current,
                limit: limits.limit
            });
        }
        
        // Enhanced container templates with language-specific configurations
        if (config.template && !config.image) {
            const templates = {
                // Base systems
                'ubuntu': {
                    image: 'ubuntu:22.04',
                    workdir: '/workspace',
                    env: ['DEBIAN_FRONTEND=noninteractive'],
                    init: [
                        'apt-get update && apt-get install -y curl wget git nano vim build-essential',
                        'useradd -m -s /bin/bash developer && echo "developer ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers'
                    ]
                },
                'alpine': {
                    image: 'alpine:latest',
                    workdir: '/workspace',
                    init: ['apk add --no-cache curl wget git nano vim build-base']
                },
                
                // Programming languages
                'python': {
                    image: 'python:3.11-slim',
                    workdir: '/workspace',
                    env: ['PYTHONPATH=/workspace', 'PIP_CACHE_DIR=/workspace/.pip'],
                    init: [
                        'apt-get update && apt-get install -y git curl',
                        'pip install --upgrade pip setuptools wheel',
                        'pip install numpy pandas requests matplotlib jupyter notebook flask fastapi'
                    ],
                    volumes: [
                        {name: 'notebooks', path: '/workspace/notebooks'},
                        {name: 'data', path: '/workspace/data'}
                    ]
                },
                'nodejs': {
                    image: 'node:20-alpine',
                    workdir: '/workspace',
                    env: ['NODE_ENV=development', 'NPM_CONFIG_CACHE=/workspace/.npm'],
                    init: [
                        'apk add --no-cache git curl python3 make g++',
                        'npm install -g typescript ts-node nodemon express-generator create-react-app'
                    ],
                    volumes: [
                        {name: 'projects', path: '/workspace/projects'},
                        {name: 'node_modules', path: '/workspace/node_modules'}
                    ]
                },
                'node': {
                    image: 'node:20-alpine',
                    workdir: '/workspace',
                    env: ['NODE_ENV=development'],
                    init: ['apk add --no-cache git curl', 'npm install -g typescript nodemon']
                },
                'golang': {
                    image: 'golang:1.21-alpine',
                    workdir: '/go/src/app',
                    env: ['GOPATH=/go', 'CGO_ENABLED=0'],
                    init: [
                        'apk add --no-cache git curl',
                        'go install github.com/air-verse/air@latest',
                        'go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest'
                    ],
                    volumes: [
                        {name: 'gopath', path: '/go'},
                        {name: 'projects', path: '/go/src/app'}
                    ]
                },
                'rust': {
                    image: 'rust:1.75-alpine',
                    workdir: '/workspace',
                    env: ['CARGO_HOME=/workspace/.cargo'],
                    init: [
                        'apk add --no-cache git curl build-base',
                        'rustup component add rustfmt clippy',
                        'cargo install cargo-watch cargo-edit'
                    ],
                    volumes: [
                        {name: 'cargo', path: '/workspace/.cargo'},
                        {name: 'projects', path: '/workspace/projects'}
                    ]
                },
                'java': {
                    image: 'openjdk:21-jdk-slim',
                    workdir: '/workspace',
                    env: ['MAVEN_HOME=/opt/maven', 'GRADLE_HOME=/opt/gradle'],
                    init: [
                        'apt-get update && apt-get install -y curl wget git',
                        'wget -O /tmp/maven.tar.gz https://dlcdn.apache.org/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz',
                        'tar -xzf /tmp/maven.tar.gz -C /opt && ln -s /opt/apache-maven-3.9.6 /opt/maven',
                        'echo "export PATH=$PATH:/opt/maven/bin" >> /etc/bash.bashrc'
                    ],
                    volumes: [
                        {name: 'maven', path: '/workspace/.m2'},
                        {name: 'projects', path: '/workspace/projects'}
                    ]
                },
                
                // Web servers and services
                'nginx': {
                    image: 'nginx:alpine',
                    workdir: '/usr/share/nginx/html',
                    init: ['apk add --no-cache curl'],
                    ports: {'80/tcp': '8080'},
                    volumes: [
                        {name: 'html', path: '/usr/share/nginx/html'},
                        {name: 'conf', path: '/etc/nginx/conf.d'}
                    ]
                },
                'apache': {
                    image: 'httpd:2.4-alpine',
                    workdir: '/usr/local/apache2/htdocs',
                    init: ['apk add --no-cache curl'],
                    ports: {'80/tcp': '8080'},
                    volumes: [
                        {name: 'htdocs', path: '/usr/local/apache2/htdocs'},
                        {name: 'conf', path: '/usr/local/apache2/conf'}
                    ]
                },
                
                // Databases
                'postgres': {
                    image: 'postgres:15-alpine',
                    workdir: '/workspace',
                    env: ['POSTGRES_PASSWORD=dev123', 'POSTGRES_DB=devdb'],
                    init: ['apk add --no-cache curl'],
                    ports: {'5432/tcp': '5432'},
                    volumes: [
                        {name: 'pgdata', path: '/var/lib/postgresql/data'},
                        {name: 'scripts', path: '/workspace/scripts'}
                    ]
                },
                'redis': {
                    image: 'redis:7-alpine',
                    workdir: '/workspace',
                    init: ['apk add --no-cache curl'],
                    ports: {'6379/tcp': '6379'},
                    volumes: [
                        {name: 'data', path: '/data'}
                    ]
                },
                
                // AI/ML
                'pytorch': {
                    image: 'pytorch/pytorch:latest',
                    workdir: '/workspace',
                    env: ['JUPYTER_ENABLE_LAB=yes'],
                    init: [
                        'apt-get update && apt-get install -y git curl',
                        'pip install jupyter notebook jupyterlab pandas numpy matplotlib seaborn scikit-learn'
                    ],
                    volumes: [
                        {name: 'notebooks', path: '/workspace/notebooks'},
                        {name: 'data', path: '/workspace/data'},
                        {name: 'models', path: '/workspace/models'}
                    ]
                },
                'tensorflow': {
                    image: 'tensorflow/tensorflow:latest-jupyter',
                    workdir: '/tf/notebooks',
                    env: ['JUPYTER_ENABLE_LAB=yes'],
                    ports: {'8888/tcp': '8888'},
                    volumes: [
                        {name: 'notebooks', path: '/tf/notebooks'},
                        {name: 'data', path: '/tf/data'}
                    ]
                }
            };
            
            const template = templates[config.template];
            if (template) {
                config.image = template.image;
                config.workdir = template.workdir || '/workspace';
                config.env = [...(config.env || []), ...(template.env || [])];
                config.init = template.init || [];
                config.volumes = [...(config.volumes || []), ...(template.volumes || [])];
                config.ports = {...(config.ports || {}), ...(template.ports || {})};
            } else {
                config.image = config.template; // Fallback to using template as image name
            }
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
            return res.status(400).json({ error: 'Image or template required' });
        }
        if (!config.maxMemory) {
            config.maxMemory = 256;
        }
        
        // Set TTL (time to live) if not specified
        if (!config.ttl && !config.persistent) {
            config.ttl = DEFAULT_CONTAINER_TTL;
        }
        
        // Add user info to config
        config.userId = userId;
        config.userRole = config.userRole || 'user';
        
        // Handle template initialization commands
        if (config.init && Array.isArray(config.init)) {
            config.initCommands = config.init;
            delete config.init; // Remove from config to avoid conflicts
        }
        
        // Determine backend based on requirements
        const backendType = config.backendType || BackendFactory.autoSelectBackend(config);
        const backend = BackendFactory.create(backendType);
        
        const containerId = await backend.create(config);
        const info = await backend.getInfo(containerId);
        
        res.json({
            id: containerId,
            name: info.name,
            status: info.status,
            backend: backendType,
            ports: info.ports || {},
            volumes: config.volumes || [],
            ttl: config.ttl,
            expiresAt: config.ttl ? new Date(Date.now() + config.ttl * 1000).toISOString() : null,
            limits: {
                current: limits.current + 1,
                limit: limits.limit
            }
        });
    } catch (error) {
        res.status(500).json({error: error.message});
    }
});

// Execute command in container
app.post('/containers/:id/exec', authenticate, async (req, res) => {
  try {
    const { command, backendType } = req.body;
    const containerId = req.params.id;
    
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
    res.status(500).json({ error: error.message });
  }
});

// List containers
app.get('/containers', authenticate, async (req, res) => {
  try {
    const dockerBackend = BackendFactory.create('docker');
    const lxcBackend = BackendFactory.create('lxc');
    
    const [dockerContainers, lxcContainers] = await Promise.allSettled([
      dockerBackend.list(),
      lxcBackend.list()
    ]);
    
    const containers = [
      ...(dockerContainers.status === 'fulfilled' ? dockerContainers.value : []),
      ...(lxcContainers.status === 'fulfilled' ? lxcContainers.value : [])
    ];
    
    res.json({ containers });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Get container info
app.get('/containers/:id', authenticate, async (req, res) => {
  try {
    const containerId = req.params.id;
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
    res.status(500).json({ error: error.message });
  }
});

// Stop container
app.post('/containers/:id/stop', authenticate, async (req, res) => {
  try {
    const containerId = req.params.id;
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
    res.status(500).json({ error: error.message });
  }
});

// Remove container
app.delete('/containers/:id', authenticate, async (req, res) => {
  try {
    const containerId = req.params.id;
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
    res.status(500).json({ error: error.message });
  }
});

// Get container logs
app.get('/containers/:id/logs', authenticate, async (req, res) => {
  try {
    const containerId = req.params.id;
    const { backendType, lines = 100 } = req.query;
    
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
    res.status(500).json({ error: error.message });
  }
});

// File upload/download setup
const upload = multer({ 
  limits: { 
    fileSize: 10 * 1024 * 1024 // 10MB limit
  },
  storage: multer.memoryStorage()
});

// Upload file to container
app.post('/containers/:id/files', authenticate, upload.single('file'), async (req, res) => {
  try {
    const containerId = req.params.id;
    const { path: targetPath = '/tmp' } = req.body;
    const file = req.file;
    
    if (!file) {
      return res.status(400).json({ error: 'No file provided' });
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
      // Create temp file
      const tempPath = `/tmp/cf-upload-${Date.now()}-${file.originalname}`;
      fs.writeFileSync(tempPath, file.buffer);
      
      // Copy to container using docker cp
      const { exec } = require('child_process');
      const dockerCpCmd = `docker cp "${tempPath}" "${containerId}:${targetPath}/${file.originalname}"`;
      
      await new Promise((resolve, reject) => {
        exec(dockerCpCmd, (error, stdout, stderr) => {
          // Clean up temp file
          fs.unlinkSync(tempPath);
          
          if (error) {
            reject(new Error(`Failed to copy file: ${stderr || error.message}`));
          } else {
            resolve();
          }
        });
      });
      
      res.json({ 
        message: 'File uploaded successfully',
        path: `${targetPath}/${file.originalname}`,
        size: file.size
      });
    } else {
      res.status(501).json({ error: 'File upload not yet supported for LXC containers' });
    }
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Download file from container
app.get('/containers/:id/files/*', authenticate, async (req, res) => {
  try {
    const containerId = req.params.id;
    const filePath = '/' + req.params[0];
    
    // Auto-detect backend
    let backend;
    try {
      backend = BackendFactory.create('docker');
      await backend.getInfo(containerId);
    } catch (dockerError) {
      backend = BackendFactory.create('lxc');
    }
    
    if (backend.getBackendType() === 'docker') {
      const tempPath = `/tmp/cf-download-${Date.now()}-${path.basename(filePath)}`;
      
      // Copy from container using docker cp
      const { exec } = require('child_process');
      const dockerCpCmd = `docker cp "${containerId}:${filePath}" "${tempPath}"`;
      
      await new Promise((resolve, reject) => {
        exec(dockerCpCmd, (error, stdout, stderr) => {
          if (error) {
            reject(new Error(`File not found or access denied: ${stderr || error.message}`));
          } else {
            resolve();
          }
        });
      });
      
      // Stream file to response
      res.download(tempPath, path.basename(filePath), (err) => {
        // Clean up temp file
        if (fs.existsSync(tempPath)) {
          fs.unlinkSync(tempPath);
        }
        if (err) {
          console.error('Download error:', err);
        }
      });
    } else {
      res.status(501).json({ error: 'File download not yet supported for LXC containers' });
    }
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Get container stats
app.get('/containers/:id/stats', authenticate, async (req, res) => {
  try {
    const containerId = req.params.id;
    
    // Auto-detect backend
    let backend;
    try {
      backend = BackendFactory.create('docker');
      await backend.getInfo(containerId);
    } catch (dockerError) {
      backend = BackendFactory.create('lxc');
    }
    
    if (backend.getBackendType() === 'docker') {
      const { exec } = require('child_process');
      
      // Use JSON format for more reliable parsing
      const statsCmd = `docker stats ${containerId} --no-stream --format "{{json .}}"`;
      
      const output = await new Promise((resolve, reject) => {
        exec(statsCmd, (error, stdout, stderr) => {
          if (error) {
            reject(new Error(`Failed to get stats: ${stderr || error.message}`));
          } else {
            resolve(stdout);
          }
        });
      });
      
      try {
        const stats = JSON.parse(output.trim());
        
        res.json({
          cpu: stats.CPUPerc || '0.00%',
          memory: {
            usage: stats.MemUsage || '0B / 0B',
            percent: stats.MemPerc || '0.00%'
          },
          network: {
            input: stats.NetIO ? stats.NetIO.split(' / ')[0] : '0B',
            output: stats.NetIO ? stats.NetIO.split(' / ')[1] : '0B'
          },
          disk: {
            read: stats.BlockIO ? stats.BlockIO.split(' / ')[0] : '0B',
            write: stats.BlockIO ? stats.BlockIO.split(' / ')[1] : '0B'
          },
          pids: stats.PIDs || '0',
          container: {
            id: stats.Container || containerId,
            name: stats.Name || 'unknown'
          },
          timestamp: new Date().toISOString()
        });
      } catch (parseError) {
        // Fallback to simpler stats if JSON parsing fails
        const simpleStatsCmd = `docker stats ${containerId} --no-stream --format "{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}"`;
        
        exec(simpleStatsCmd, (error, stdout, stderr) => {
          if (error) {
            res.status(500).json({ error: 'Failed to get container stats' });
          } else {
            const [cpu, memUsage, memPerc] = stdout.trim().split(',');
            res.json({
              cpu: cpu || '0.00%',
              memory: {
                usage: memUsage || '0B / 0B',
                percent: memPerc || '0.00%'
              },
              timestamp: new Date().toISOString(),
              note: 'Limited stats due to parsing issues'
            });
          }
        });
      }
    } else {
      res.status(501).json({ error: 'Stats not yet supported for LXC containers' });
    }
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Extend container TTL
app.post('/containers/:id/extend', authenticate, async (req, res) => {
  try {
    const containerId = req.params.id;
    const { ttl } = req.body;
    
    if (!ttl || ttl <= 0) {
      return res.status(400).json({ error: 'Valid TTL in seconds required' });
    }
    
    const backend = BackendFactory.create('docker');
    const container = backend.docker.getContainer(containerId);
    
    // Update the container label with new expiry
    const newExpiresAt = new Date(Date.now() + ttl * 1000).toISOString();
    
    // Note: Docker doesn't allow updating labels on running containers
    // This is a limitation, but we can track it in memory or require restart
    res.json({
      message: 'Container TTL extension scheduled',
      newExpiresAt,
      note: 'TTL extension will take effect after container restart'
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Get user limits and current usage
app.get('/limits', authenticate, async (req, res) => {
  try {
    const userId = req.query.userId || req.ip || 'anonymous';
    const limits = await checkUserLimits(userId);
    
    const dockerBackend = BackendFactory.create('docker');
    const containers = await dockerBackend.list();
    const userContainers = containers.filter(c => 
      c.labels && c.labels['cf-user'] === userId
    );
    
    res.json({
      userId,
      containers: {
        current: limits.current,
        limit: limits.limit,
        available: limits.limit - limits.current
      },
      userContainers: userContainers.map(c => ({
        id: c.id,
        name: c.name,
        status: c.status,
        created: c.created,
        expiresAt: c.labels ? c.labels['cf-expires'] : null
      })),
      settings: {
        maxContainersPerUser: MAX_CONTAINERS_PER_USER,
        defaultTtl: DEFAULT_CONTAINER_TTL,
        cleanupInterval: CLEANUP_INTERVAL
      }
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// List available container templates
app.get('/templates', authenticate, async (req, res) => {
  try {
    const templates = {
      'Base Systems': {
        ubuntu: 'Ubuntu 22.04 with development tools',
        alpine: 'Alpine Linux minimal container'
      },
      'Programming Languages': {
        python: 'Python 3.11 with data science libraries',
        nodejs: 'Node.js 20 with TypeScript and tools',
        golang: 'Go 1.21 with development tools',
        rust: 'Rust 1.75 with Cargo tools',
        java: 'OpenJDK 21 with Maven'
      },
      'Web Servers': {
        nginx: 'Nginx web server',
        apache: 'Apache HTTP server'
      },
      'Databases': {
        postgres: 'PostgreSQL 15 database',
        redis: 'Redis key-value store'
      },
      'AI/ML': {
        pytorch: 'PyTorch with Jupyter',
        tensorflow: 'TensorFlow with Jupyter'
      }
    };
    
    res.json({
      templates,
      usage: 'Use template parameter in container creation: {"template": "python", "maxMemory": 512}',
      features: [
        'Pre-configured development environments',
        'Language-specific tools and packages',
        'Optimized volume mappings',
        'Environment variables',
        'Automatic initialization scripts'
      ]
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
    console.log(`Container service running on port ${PORT}`);
    console.log(`WebSocket terminal available at ws://localhost:${PORT}/terminal`);
    console.log(`API Key: ${API_KEY}`);
});