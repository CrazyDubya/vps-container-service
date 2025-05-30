const { exec } = require('child_process');
const util = require('util');
const ContainerInterface = require('./container-interface');

const execAsync = util.promisify(exec);

/**
 * LXD implementation of the container interface
 */
class LXDBackend extends ContainerInterface {
  constructor() {
    super();
  }

  async create(config) {
    const containerName = `cf-${config.name || config.id || Math.random().toString(36).substr(2, 9)}`;
    
    try {
      // Check if LXD is available and initialized
      const { stdout: lxdStatus } = await execAsync('lxc info').catch((error) => {
        throw new Error(`LXD not available: ${error.message}`);
      });
      if (!lxdStatus.includes('api_status: stable')) {
        throw new Error('LXD not properly initialized. Please run: lxd init');
      }
      
      // Map template to LXD image
      const image = this.getImage(config.template || 'ubuntu');
      
      // Create LXD container with increased timeout
      const createCmd = `lxc launch ${image} ${containerName} --config limits.memory=${config.memory || 512}MB`;
      console.log(`Creating container: ${createCmd}`);
      
      try {
        await execAsync(createCmd, { timeout: 180000 }); // 3 min timeout
        console.log(`Container ${containerName} created successfully`);
      } catch (error) {
        console.error(`Container creation failed: ${error.message}`);
        console.error(`Full error:`, error);
        throw new Error(`Failed to create LXD container: ${error.message}`);
      }
      
      // Wait for container to be ready and check status
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      // Verify container is running
      const { stdout: statusCheck } = await execAsync(`lxc list ${containerName} --format json`);
      const containers = JSON.parse(statusCheck);
      if (containers.length === 0 || containers[0].status !== 'Running') {
        throw new Error(`Container ${containerName} failed to start properly`);
      }
      
      // Set metadata using LXD config
      await execAsync(`lxc config set ${containerName} user.cf-user-id "${config.userId || 'anonymous'}"`);
      await execAsync(`lxc config set ${containerName} user.cf-user "${config.username || 'anonymous'}"`);
      await execAsync(`lxc config set ${containerName} user.cf-role "${config.userRole || 'user'}"`);
      await execAsync(`lxc config set ${containerName} user.cf-created "${new Date().toISOString()}"`);
      
      if (config.ttl) {
        const expires = new Date(Date.now() + config.ttl * 1000);
        await execAsync(`lxc config set ${containerName} user.cf-expires "${expires.toISOString()}"`);
      }
      
      // Apply template-specific setup if specified
      if (config.template && config.template !== 'ubuntu') {
        await this.applyTemplate(containerName, config.template);
      }
      
      return {
        id: containerName,
        name: containerName
      };
    } catch (error) {
      throw new Error(`Failed to create LXD container: ${error.message}`);
    }
  }
  
  /**
   * Get appropriate LXD image name
   */
  getImage(templateName) {
    const imageMap = {
      'ubuntu': 'ubuntu:22.04',
      'alpine': 'images:alpine/3.18',
      'python': 'ubuntu:22.04',
      'node': 'ubuntu:22.04',
      'go': 'ubuntu:22.04',
      'rust': 'ubuntu:22.04',
      'java': 'ubuntu:22.04',
      'nginx': 'ubuntu:22.04',
      'postgres': 'ubuntu:22.04',
      'redis': 'ubuntu:22.04'
    };
    
    return imageMap[templateName] || 'ubuntu:22.04';
  }

  async start(id) {
    try {
      await execAsync(`lxc start ${id}`);
    } catch (error) {
      throw new Error(`Failed to start LXD container: ${error.message}`);
    }
  }

  async stop(id) {
    try {
      await execAsync(`lxc stop ${id}`);
    } catch (error) {
      throw new Error(`Failed to stop LXD container: ${error.message}`);
    }
  }

  async exec(id, command) {
    try {
      const { stdout, stderr } = await execAsync(`lxc exec ${id} -- sh -c "${command}"`);
      return {
        output: stdout + stderr,
        exitCode: 0
      };
    } catch (error) {
      return {
        output: error.stderr || error.message,
        exitCode: error.code || 1
      };
    }
  }

  async list() {
    try {
      const { stdout } = await execAsync('lxc list --format json');
      const containers = JSON.parse(stdout);
      
      return containers
        .filter(container => container.name.startsWith('cf-'))
        .map(container => ({
          id: container.name,
          name: container.name,
          image: container.config['image.description'] || 'ubuntu:22.04',
          status: container.status.toLowerCase(),
          created: container.created_at,
          labels: this.extractLabels(container.config || {})
        }));
    } catch (error) {
      throw new Error(`Failed to list LXD containers: ${error.message}`);
    }
  }

  async inspect(id) {
    try {
      const { stdout } = await execAsync(`lxc list ${id} --format json`);
      const containers = JSON.parse(stdout);
      
      if (containers.length === 0) {
        throw new Error('Container not found');
      }
      
      const container = containers[0];
      
      return {
        Id: container.name,
        Name: container.name,
        Config: {
          Image: container.config['image.description'] || 'ubuntu:22.04',
          Labels: this.extractLabels(container.config || {}),
          Env: []
        },
        State: {
          Status: container.status.toLowerCase(),
          StartedAt: container.last_used_at
        },
        Created: container.created_at,
        NetworkSettings: {
          Ports: {}
        },
        Mounts: []
      };
    } catch (error) {
      throw new Error(`Failed to inspect LXD container: ${error.message}`);
    }
  }

  async delete(id) {
    try {
      // Stop container first if running
      try {
        await execAsync(`lxc stop ${id}`);
      } catch (e) {
        // Container might already be stopped
      }
      
      // Delete container
      await execAsync(`lxc delete ${id}`);
    } catch (error) {
      throw new Error(`Failed to delete LXD container: ${error.message}`);
    }
  }

  async logs(id, lines = 100) {
    try {
      // LXD doesn't have built-in log viewing like Docker
      // Try to get recent system logs related to the container
      const { stdout } = await execAsync(`journalctl -u snap.lxd.daemon --lines=${lines} --no-pager | grep ${id}`);
      return stdout;
    } catch (error) {
      return `No logs available for container ${id}`;
    }
  }

  async stats(id) {
    try {
      const { stdout } = await execAsync(`lxc info ${id}`);
      
      // Parse basic info from lxc info output
      const lines = stdout.split('\n');
      const stats = {
        memory: { usage: 0, limit: 0 },
        cpu: { usage: 0 },
        network: { rx_bytes: 0, tx_bytes: 0 }
      };
      
      for (const line of lines) {
        if (line.includes('Memory usage:')) {
          const match = line.match(/(\d+\.\d+)MB/);
          if (match) stats.memory.usage = parseFloat(match[1]) * 1024 * 1024;
        }
      }
      
      return stats;
    } catch (error) {
      throw new Error(`Failed to get LXD container stats: ${error.message}`);
    }
  }

  async copyTo(containerId, sourcePath, targetPath) {
    try {
      await execAsync(`lxc file push ${sourcePath} ${containerId}${targetPath}`);
    } catch (error) {
      throw new Error(`Failed to copy file to container: ${error.message}`);
    }
  }

  async copyFrom(containerId, sourcePath, targetPath) {
    try {
      await execAsync(`lxc file pull ${containerId}${sourcePath} ${targetPath}`);
    } catch (error) {
      throw new Error(`Failed to copy file from container: ${error.message}`);
    }
  }

  async attachInteractive(containerId) {
    // For WebSocket terminals, we'd need a more complex implementation
    // For now, return a mock object that can be used for basic command execution
    return {
      input: {
        write: (data) => {
          // Would need to implement interactive shell session
          console.log('Terminal input:', data.toString());
        },
        end: () => {
          console.log('Terminal session ended');
        }
      },
      output: {
        on: (event, callback) => {
          if (event === 'data') {
            // Would need to implement real-time output streaming
            setTimeout(() => callback('LXD terminal ready\n$ '), 100);
          }
        }
      }
    };
  }

  /**
   * Apply a template to the container
   */
  async applyTemplate(containerName, template) {
    const templates = {
      'python': [
        'apt update',
        'apt install -y python3 python3-pip',
        'pip3 install --upgrade pip',
        'pip3 install requests numpy pandas matplotlib jupyter ipython',
        'mkdir -p /workspace'
      ],
      'node': [
        'apt update',
        'apt install -y curl',
        'curl -fsSL https://deb.nodesource.com/setup_20.x | bash -',
        'apt install -y nodejs',
        'npm install -g yarn pnpm nodemon pm2',
        'mkdir -p /workspace'
      ],
      'go': [
        'apt update',
        'apt install -y wget git',
        'wget -O- https://golang.org/dl/go1.21.0.linux-amd64.tar.gz | tar -C /usr/local -xz',
        'echo "export PATH=$PATH:/usr/local/go/bin" >> /etc/profile',
        'mkdir -p /workspace'
      ],
      'rust': [
        'apt update',
        'apt install -y curl build-essential',
        'curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y',
        'echo "source ~/.cargo/env" >> /etc/profile',
        'mkdir -p /workspace'
      ],
      'java': [
        'apt update',
        'apt install -y openjdk-21-jdk maven gradle',
        'mkdir -p /workspace'
      ],
      'nginx': [
        'apt update',
        'apt install -y nginx',
        'systemctl enable nginx',
        'mkdir -p /var/www/html'
      ],
      'postgres': [
        'apt update',
        'apt install -y postgresql postgresql-contrib',
        'systemctl enable postgresql'
      ],
      'redis': [
        'apt update',
        'apt install -y redis-server',
        'systemctl enable redis-server'
      ]
    };
    
    if (templates[template]) {
      for (const cmd of templates[template]) {
        try {
          await execAsync(`lxc exec ${containerName} -- sh -c "${cmd}"`);
        } catch (error) {
          console.error(`Template command failed: ${cmd}`, error.message);
        }
      }
    }
  }

  /**
   * Extract cf-specific labels from LXD config
   */
  extractLabels(config) {
    const labels = {};
    for (const [key, value] of Object.entries(config)) {
      if (key.startsWith('user.cf-')) {
        labels[key.replace('user.', '')] = value;
      }
    }
    return labels;
  }

  getBackendType() {
    return 'lxd';
  }
}

module.exports = LXDBackend;