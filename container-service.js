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
        
        // Handle template vs image parameter compatibility
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
            return res.status(400).json({ error: 'Image or template required' });
        }
        if (!config.maxMemory) {
            config.maxMemory = 256;
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
            ports: info.ports || {}
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
      const statsCmd = `docker stats ${containerId} --no-stream --format "table {{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}"`;
      
      const output = await new Promise((resolve, reject) => {
        exec(statsCmd, (error, stdout, stderr) => {
          if (error) {
            reject(new Error(`Failed to get stats: ${stderr || error.message}`));
          } else {
            resolve(stdout);
          }
        });
      });
      
      // Parse stats output
      const lines = output.trim().split('\n');
      if (lines.length >= 2) {
        const [cpu, memUsage, memPerc, netIO, blockIO] = lines[1].split('\t');
        
        res.json({
          cpu: cpu.trim(),
          memory: {
            usage: memUsage.trim(),
            percent: memPerc.trim()
          },
          network: netIO.trim(),
          disk: blockIO.trim(),
          timestamp: new Date().toISOString()
        });
      } else {
        res.json({ error: 'Unable to parse stats' });
      }
    } else {
      res.status(501).json({ error: 'Stats not yet supported for LXC containers' });
    }
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

const PORT = process.env.PORT || 8082;
server.listen(PORT, () => {
    console.log(`Container service running on port ${PORT}`);
    console.log(`WebSocket terminal available at ws://localhost:${PORT}/terminal`);
    console.log(`API Key: ${API_KEY}`);
});