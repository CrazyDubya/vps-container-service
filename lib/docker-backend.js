const Docker = require('dockerode');
const ContainerInterface = require('./container-interface');

/**
 * Docker implementation of the container interface
 */
class DockerBackend extends ContainerInterface {
  constructor() {
    super();
    this.docker = new Docker();
    this.networkInitialized = false;
  }

  async ensureNetwork() {
    if (this.networkInitialized) return;
    
    try {
      // Check if cf-network exists
      const networks = await this.docker.listNetworks();
      const cfNetwork = networks.find(net => net.Name === 'cf-network');
      
      if (!cfNetwork) {
        console.log('📡 Creating cf-network for containers...');
        await this.docker.createNetwork({
          Name: 'cf-network',
          Driver: 'bridge',
          EnableIPv6: false,
          IPAM: {
            Config: [{
              Subnet: '172.20.0.0/16'
            }]
          }
        });
        console.log('✅ cf-network created successfully');
      }
      
      this.networkInitialized = true;
    } catch (error) {
      console.warn('Network setup warning:', error.message);
      // Continue without custom network
    }
  }

  async pullImageIfNeeded(imageName) {
    try {
      // Check if image exists locally
      const images = await this.docker.listImages();
      const imageExists = images.some(img => 
        img.RepoTags && img.RepoTags.some(tag => tag === imageName)
      );
      
      if (!imageExists) {
        console.log(`📦 Pulling image: ${imageName}...`);
        
        return new Promise((resolve, reject) => {
          this.docker.pull(imageName, (err, stream) => {
            if (err) {
              console.error(`❌ Failed to pull image ${imageName}:`, err.message);
              reject(err);
              return;
            }
            
            // Follow the pull progress
            this.docker.modem.followProgress(stream, (err, result) => {
              if (err) {
                console.error(`❌ Error during image pull ${imageName}:`, err.message);
                reject(err);
              } else {
                console.log(`✅ Successfully pulled image: ${imageName}`);
                resolve(result);
              }
            }, (event) => {
              // Optional: Log pull progress
              if (event.status && event.progress) {
                console.log(`📦 ${imageName}: ${event.status} ${event.progress || ''}`);
              }
            });
          });
        });
      } else {
        console.log(`✅ Image ${imageName} already exists locally`);
      }
    } catch (error) {
      console.error(`❌ Error checking/pulling image ${imageName}:`, error.message);
      throw error;
    }
  }

  async create(config) {
    // Ensure network exists before creating containers
    await this.ensureNetwork();
    
    // Ensure image is available before creating container
    await this.pullImageIfNeeded(config.image);
    
    const fs = require('fs');
    const path = require('path');
    const containerName = `cf-${config.name || config.id || Math.random().toString(36).substr(2, 9)}`;
    
    // Set default command if none provided
    const defaultCmd = config.image && config.image.includes('nginx') 
      ? ['nginx', '-g', 'daemon off;'] 
      : ['sh', '-c', 'while true; do sleep 30; done'];
    
    // Create volume binds if specified
    const binds = [];
    const volumeBaseDir = path.join(__dirname, '..', 'volumes');
    
    if (config.volumes && Array.isArray(config.volumes)) {
      // Ensure base volume directory exists
      if (!fs.existsSync(volumeBaseDir)) {
        fs.mkdirSync(volumeBaseDir, { recursive: true });
      }
      
      for (const volume of config.volumes) {
        const volumeName = volume.name || `vol-${Math.random().toString(36).substr(2, 8)}`;
        const hostPath = path.join(volumeBaseDir, containerName, volumeName);
        const containerPath = volume.path || `/mnt/${volumeName}`;
        
        // Create host directory
        fs.mkdirSync(hostPath, { recursive: true });
        
        // Set proper permissions (readable/writable by container)
        try {
          fs.chmodSync(hostPath, 0o755);
        } catch (err) {
          console.warn(`Could not set permissions on ${hostPath}:`, err.message);
        }
        
        binds.push(`${hostPath}:${containerPath}`);
      }
    }
    
    // Add persistent workspace volume by default
    if (config.persistent !== false) {
      const workspaceHost = path.join(volumeBaseDir, containerName, 'workspace');
      fs.mkdirSync(workspaceHost, { recursive: true });
      fs.chmodSync(workspaceHost, 0o755);
      binds.push(`${workspaceHost}:/workspace`);
    }
    
    const container = await this.docker.createContainer({
      name: containerName,
      Image: config.image,
      Cmd: config.cmd || defaultCmd,
      Env: config.env || [],
      WorkingDir: config.workdir || '/workspace',
      HostConfig: {
        Memory: parseInt(config.maxMemory) * 1024 * 1024,
        MemorySwap: parseInt(config.maxMemory) * 1024 * 1024,
        NetworkMode: this.networkInitialized ? "cf-network" : "bridge",
        AutoRemove: !config.persistent,
        Binds: binds.length > 0 ? binds : undefined,
        // Resource limits
        CpuShares: config.cpuShares || 1024,
        CpuQuota: config.cpuQuota || undefined,
        CpuPeriod: config.cpuPeriod || undefined
      },
      Labels: {
        "cf-user": config.userId || 'anonymous',
        "cf-role": config.userRole || 'user',
        "cf-type": "docker",
        "cf-created": new Date().toISOString(),
        "cf-expires": config.ttl ? new Date(Date.now() + config.ttl * 1000).toISOString() : undefined,
        "cf-volumes": binds.join(',')
      }
    });
    
    await container.start();
    const info = await container.inspect();
    
    return {
      id: info.Id,
      name: info.Name.replace('/', ''),
      status: info.State.Status
    };
  }

  async start(id) {
    const container = this.docker.getContainer(id);
    await container.start();
  }

  async stop(id) {
    const container = this.docker.getContainer(id);
    await container.stop();
  }

  async exec(id, command) {
    const container = this.docker.getContainer(id);

    // Use sh -c to properly handle complex commands with pipes and redirections
    const cmd = ['sh', '-c', command];

    // Create exec instance
    const exec = await container.exec({
      Cmd: cmd,
      AttachStdout: true,
      AttachStderr: true,
      Tty: false  // Disable TTY to avoid control sequences
    });

    // Start exec and get output
    const stream = await exec.start({ 
      hijack: true,
      stdin: false
    });

    let stdout = '';
    let stderr = '';

    // Properly handle Docker multiplexed stream
    // Docker uses a simple 8-byte header format for each frame
    const chunks = [];
    
    stream.on('data', (chunk) => {
      chunks.push(chunk);
    });
    
    stream.on('end', () => {
      const fullBuffer = Buffer.concat(chunks);
      let offset = 0;
      
      while (offset < fullBuffer.length) {
        if (fullBuffer.length - offset < 8) break;
        
        const streamType = fullBuffer[offset];
        const frameSize = fullBuffer.readUInt32BE(offset + 4);
        
        if (fullBuffer.length - offset < 8 + frameSize) break;
        
        const frame = fullBuffer.subarray(offset + 8, offset + 8 + frameSize);
        
        if (streamType === 1) { // stdout
          stdout += frame.toString('utf8');
        } else if (streamType === 2) { // stderr
          stderr += frame.toString('utf8');
        }
        
        offset += 8 + frameSize;
      }
      
      // If no multiplexed data found, treat as raw stdout
      if (stdout === '' && stderr === '' && fullBuffer.length > 0) {
        stdout = fullBuffer.toString('utf8');
      }
    });

    // Wait for stream to end and get exit code
    await new Promise((resolve) => {
      stream.on('end', resolve);
    });

    const execInfo = await exec.inspect();

    return {
      output: stdout,
      error: stderr,
      exitCode: execInfo.ExitCode || 0
    };
  }

  async list() {
    const containers = await this.docker.listContainers({ 
      all: true,
      filters: { label: ['cf-type=docker'] }
    });
    
    return containers.map(container => ({
      id: container.Id,
      name: (container.Names && container.Names[0]) ? container.Names[0].replace('/', '') : container.Id.substring(0, 12),
      image: container.Image,
      status: container.State,
      created: container.Created,
      labels: container.Labels || {}
    }));
  }

  async getInfo(id) {
    const container = this.docker.getContainer(id);
    const info = await container.inspect();
    
    return {
      id: info.Id,
      name: info.Name.replace('/', ''),
      image: info.Config.Image,
      status: info.State.Status,
      created: info.Created,
      ports: info.NetworkSettings.Ports,
      labels: info.Config.Labels
    };
  }

  async remove(id) {
    const container = this.docker.getContainer(id);
    await container.remove({ force: true });
  }

  async inspect(id) {
    const container = this.docker.getContainer(id);
    return await container.inspect();
  }

  async getLogs(id, lines = 100) {
    const container = this.docker.getContainer(id);
    const logs = await container.logs({
      stdout: true,
      stderr: true,
      tail: lines
    });
    
    return logs.toString();
  }

  async stats(id) {
    const container = this.docker.getContainer(id);
    const stats = await container.stats({ stream: false });
    
    // Transform Docker stats to standard format
    return {
      cpu: {
        usage: stats.cpu_stats.cpu_usage.total_usage,
        percent: this.calculateCpuPercent(stats)
      },
      memory: {
        usage: stats.memory_stats.usage,
        limit: stats.memory_stats.limit,
        percent: (stats.memory_stats.usage / stats.memory_stats.limit) * 100
      },
      network: stats.networks || {},
      timestamp: new Date().toISOString()
    };
  }

  calculateCpuPercent(stats) {
    const cpuDelta = stats.cpu_stats.cpu_usage.total_usage - stats.precpu_stats.cpu_usage.total_usage;
    const systemDelta = stats.cpu_stats.system_cpu_usage - stats.precpu_stats.system_cpu_usage;
    const numberCpus = stats.cpu_stats.online_cpus || 1;
    
    if (systemDelta > 0 && cpuDelta > 0) {
      return (cpuDelta / systemDelta) * numberCpus * 100;
    }
    return 0;
  }

  getBackendType() {
    return 'docker';
  }
}

module.exports = DockerBackend;