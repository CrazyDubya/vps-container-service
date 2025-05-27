const Docker = require('dockerode');
const ContainerInterface = require('./container-interface');

/**
 * Docker implementation of the container interface
 */
class DockerBackend extends ContainerInterface {
  constructor() {
    super();
    this.docker = new Docker();
  }

  async create(config) {
    const containerName = `cf-${config.name || config.id || Math.random().toString(36).substr(2, 9)}`;
    
    // Set default command if none provided
    const defaultCmd = config.image && config.image.includes('nginx') 
      ? ['nginx', '-g', 'daemon off;'] 
      : ['sh', '-c', 'while true; do sleep 30; done'];
    
    const container = await this.docker.createContainer({
      name: containerName,
      Image: config.image,
      Cmd: config.cmd || defaultCmd,
      Env: config.env || [],
      HostConfig: {
        Memory: parseInt(config.maxMemory) * 1024 * 1024,
        MemorySwap: parseInt(config.maxMemory) * 1024 * 1024,
        NetworkMode: "cf-network",
        AutoRemove: !config.persistent
      },
      Labels: {
        "cf-user": config.userId,
        "cf-role": config.userRole,
        "cf-type": "docker",
        "cf-created": new Date().toISOString()
      }
    });
    
    await container.start();
    const info = await container.inspect();
    
    return info.Id;
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

    // Docker multiplexes stdout/stderr in the stream
    // First 8 bytes are header: [stream_type, 0, 0, 0, size1, size2, size3, size4]
    stream.on('data', (chunk) => {
      let offset = 0;
      while (offset < chunk.length) {
        if (chunk.length - offset < 8) break; // Not enough data for header
        
        const streamType = chunk[offset];
        const size = chunk.readUInt32BE(offset + 4);
        
        if (chunk.length - offset < 8 + size) break; // Not enough data for payload
        
        const payload = chunk.slice(offset + 8, offset + 8 + size);
        
        if (streamType === 1) { // stdout
          stdout += payload.toString('utf8');
        } else if (streamType === 2) { // stderr
          stderr += payload.toString('utf8');
        }
        
        offset += 8 + size;
      }
    });

    // Wait for stream to end and get exit code
    const [result] = await Promise.all([
      new Promise((resolve) => {
        stream.on('end', resolve);
      }),
      exec.inspect()
    ]);

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
      name: container.Names[0].replace('/', ''),
      image: container.Image,
      status: container.State,
      created: container.Created,
      labels: container.Labels
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

  async getLogs(id, lines = 100) {
    const container = this.docker.getContainer(id);
    const logs = await container.logs({
      stdout: true,
      stderr: true,
      tail: lines
    });
    
    return logs.toString();
  }

  getBackendType() {
    return 'docker';
  }
}

module.exports = DockerBackend;