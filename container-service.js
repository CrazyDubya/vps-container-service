const express = require("express");
const Docker = require("dockerode");
const crypto = require("crypto");

const app = express();
const docker = new Docker();

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
        const containerName = `cf-${config.id}`;
        
        const container = await docker.createContainer({
            name: containerName,
            Image: config.image,
            Cmd: config.cmd,
            Env: config.env || [],
            HostConfig: {
                Memory: parseInt(config.maxMemory) * 1024 * 1024,
                // Removed CPU quota settings to avoid cgroup errors
                // CpuQuota: parseInt(config.maxCpu * 100000),
                // CpuPeriod: 100000,
                NetworkMode: "cf-network",
                AutoRemove: true
            },
            Labels: {
                "cf-user": config.userId,
                "cf-role": config.userRole,
                "cf-created": new Date().toISOString()
            }
        });
        
        await container.start();
        const info = await container.inspect();
        
        res.json({
            id: info.Id,
            name: containerName,
            status: "running",
            ports: info.NetworkSettings.Ports
        });
    } catch (error) {
        res.status(500).json({error: error.message});
    }
});

// Execute command in container
app.post('/containers/:id/exec', authenticate, async (req, res) => {
  try {
    const { command } = req.body;
    const container = docker.getContainer(req.params.id);

    // Create exec instance
    const exec = await container.exec({
      Cmd: command.split(' '),
      AttachStdout: true,
      AttachStderr: true
    });

    // Start exec and get output
    const stream = await exec.start({ hijack: true });

    let output = '';
    stream.on('data', (chunk) => {
      output += chunk.toString();
    });

    await new Promise((resolve) => {
      stream.on('end', resolve);
    });

    res.json({
      output: output,
      exitCode: 0
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

const PORT = 8080;
app.listen(PORT, () => {
    console.log(`Container service running on port ${PORT}`);
    console.log(`API Key: ${API_KEY}`);
});