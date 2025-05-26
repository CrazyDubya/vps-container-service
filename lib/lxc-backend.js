const { exec } = require('child_process');
const util = require('util');
const ContainerInterface = require('./container-interface');

const execAsync = util.promisify(exec);

/**
 * LXC implementation of the container interface
 */
class LXCBackend extends ContainerInterface {
  constructor() {
    super();
  }

  async create(config) {
    const containerName = `cf-${config.id}`;
    
    try {
      // Create LXC container
      await execAsync(`lxc launch ubuntu:22.04 ${containerName}`);
      
      // Wait for container to be ready
      await execAsync(`lxc exec ${containerName} -- cloud-init status --wait`);
      
      // Apply template if specified
      if (config.template) {
        await this.applyTemplate(containerName, config.template);
      }
      
      // Set resource limits
      if (config.maxMemory) {
        await execAsync(`lxc config set ${containerName} limits.memory ${config.maxMemory}MB`);
      }
      
      if (config.maxCpu) {
        await execAsync(`lxc config set ${containerName} limits.cpu ${config.maxCpu}`);
      }
      
      // Add labels as config
      await execAsync(`lxc config set ${containerName} user.cf-user "${config.userId}"`);
      await execAsync(`lxc config set ${containerName} user.cf-role "${config.userRole}"`);
      await execAsync(`lxc config set ${containerName} user.cf-type "lxc"`);
      await execAsync(`lxc config set ${containerName} user.cf-created "${new Date().toISOString()}"`);
      
      return containerName;
    } catch (error) {
      throw new Error(`Failed to create LXC container: ${error.message}`);
    }
  }

  async start(id) {
    try {
      await execAsync(`lxc start ${id}`);
    } catch (error) {
      throw new Error(`Failed to start LXC container: ${error.message}`);
    }
  }

  async stop(id) {
    try {
      await execAsync(`lxc stop ${id}`);
    } catch (error) {
      throw new Error(`Failed to stop LXC container: ${error.message}`);
    }
  }

  async exec(id, command) {
    try {
      const { stdout, stderr } = await execAsync(`lxc exec ${id} -- ${command}`);
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
          status: container.status,
          created: container.created_at,
          labels: this.extractLabels(container.config)
        }));
    } catch (error) {
      throw new Error(`Failed to list LXC containers: ${error.message}`);
    }
  }

  async getInfo(id) {
    try {
      const { stdout } = await execAsync(`lxc info ${id} --format json`);
      const info = JSON.parse(stdout);
      
      return {
        id: info.name,
        name: info.name,
        image: info.config['image.description'] || 'ubuntu:22.04',
        status: info.status,
        created: info.created_at,
        ports: info.state?.network || {},
        labels: this.extractLabels(info.config)
      };
    } catch (error) {
      throw new Error(`Failed to get LXC container info: ${error.message}`);
    }
  }

  async remove(id) {
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
      throw new Error(`Failed to remove LXC container: ${error.message}`);
    }
  }

  async getLogs(id, lines = 100) {
    try {
      const { stdout } = await execAsync(`lxc info ${id} --show-log`);
      const logLines = stdout.split('\n');
      return logLines.slice(-lines).join('\n');
    } catch (error) {
      throw new Error(`Failed to get LXC container logs: ${error.message}`);
    }
  }

  /**
   * Apply a template to the container
   * @param {string} containerName - Container name
   * @param {string} template - Template to apply
   */
  async applyTemplate(containerName, template) {
    const templates = {
      'node-express': [
        'apt update',
        'apt install -y nodejs npm',
        'mkdir -p /workspace',
        'npm install -g express nodemon'
      ],
      'python-flask': [
        'apt update', 
        'apt install -y python3 python3-pip',
        'pip3 install flask gunicorn',
        'mkdir -p /workspace'
      ],
      'html-css-js': [
        'apt update',
        'apt install -y nginx',
        'mkdir -p /var/www/html',
        'systemctl enable nginx'
      ],
      'development-vps': [
        'apt update',
        'apt install -y curl wget git vim nano htop',
        'apt install -y build-essential',
        'mkdir -p /workspace'
      ]
    };
    
    if (templates[template]) {
      for (const cmd of templates[template]) {
        await execAsync(`lxc exec ${containerName} -- ${cmd}`);
      }
    }
  }

  /**
   * Extract cf-specific labels from LXC config
   * @param {Object} config - LXC container config
   * @returns {Object} Extracted labels
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
    return 'lxc';
  }
}

module.exports = LXCBackend;