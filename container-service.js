const express = require("express");
const crypto = require("crypto");
const BackendFactory = require("./lib/backend-factory");

const app = express();

app.use(express.json());

const API_KEY = process.env.API_KEY || crypto.randomBytes(32).toString("hex");
console.log("API Key:", API_KEY);

const authenticate = (req, res, next) => {
    if (req.headers["x-api-key"] !== API_KEY) {
        return res.status(401).json({error: "Unauthorized"});
    }
    next();
};

app.get("/health", (req, res) => {
    res.json({
        status: "healthy",
        timestamp: new Date().toISOString()
    });
});

app.post("/containers/create", authenticate, async (req, res) => {
    try {
        const config = req.body;
        
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

const PORT = 8080;
app.listen(PORT, () => {
    console.log(`Container service running on port ${PORT}`);
    console.log(`API Key: ${API_KEY}`);
});