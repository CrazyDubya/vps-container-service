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
      // Check if LXC is available
      const { stdout: lxcStatus } = await execAsync('which lxc-create').catch(() => ({ stdout: '' }));
      if (!lxcStatus.trim()) {
        throw new Error('LXC not properly installed. Please install: apt install lxc-utils lxc-templates');
      }
      
      // Determine template based on config or default to ubuntu
      const template = this.getTemplate(config.template || 'ubuntu');
      
      // Create LXC container using template
      await execAsync(`lxc-create -t ${template} -n ${containerName}`, { timeout: 300000 }); // 5 min timeout
      
      // Start the container
      await execAsync(`lxc-start -n ${containerName} -d`);
      
      // Wait for container to be ready (give it some time to boot)
      await new Promise(resolve => setTimeout(resolve, 5000));
      
      // Apply template-specific setup if specified
      if (config.template && config.template !== 'ubuntu') {
        await this.applyTemplate(containerName, config.template);
      }
      
      // Store metadata in a simple way (LXC doesn't have built-in metadata like LXD)
      const metadataDir = `/var/lib/lxc/${containerName}/cf-metadata`;
      await execAsync(`mkdir -p ${metadataDir}`);
      await execAsync(`echo "${config.userId}" > ${metadataDir}/user`);
      await execAsync(`echo "${config.userRole}" > ${metadataDir}/role`);
      await execAsync(`echo "lxc" > ${metadataDir}/type`);
      await execAsync(`echo "${new Date().toISOString()}" > ${metadataDir}/created`);
      
      return containerName;
    } catch (error) {
      throw new Error(`Failed to create LXC container: ${error.message}`);
    }
  }
  
  /**
   * Get appropriate LXC template name
   */
  getTemplate(templateName) {
    const templateMap = {
      'ubuntu': 'ubuntu',
      'node-express': 'ubuntu',
      'python-flask': 'ubuntu', 
      'html-css-js': 'ubuntu',
      'development-vps': 'ubuntu',
      'alpine': 'alpine',
      'debian': 'debian'
    };
    
    return templateMap[templateName] || 'ubuntu';
  }

  async start(id) {
    try {
      await execAsync(`lxc-start -n ${id} -d`);
    } catch (error) {
      throw new Error(`Failed to start LXC container: ${error.message}`);
    }
  }

  async stop(id) {
    try {
      await execAsync(`lxc-stop -n ${id}`);
    } catch (error) {
      throw new Error(`Failed to stop LXC container: ${error.message}`);
    }
  }

  async exec(id, command) {
    try {
      const { stdout, stderr } = await execAsync(`lxc-attach -n ${id} -- ${command}`);
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
      const { stdout } = await execAsync('lxc-ls -f');
      const lines = stdout.trim().split('\n');
      
      if (lines.length <= 1) return []; // No containers or just header
      
      const containers = [];
      for (let i = 1; i < lines.length; i++) { // Skip header
        const parts = lines[i].trim().split(/\s+/);
        if (parts.length >= 2 && parts[0].startsWith('cf-')) {
          const name = parts[0];
          const status = parts[1];
          
          // Try to get metadata
          const labels = await this.getMetadata(name);
          
          containers.push({
            id: name,
            name: name,
            image: 'ubuntu:22.04', // LXC doesn't track original image
            status: status.toLowerCase(),
            created: labels['cf-created'] || 'unknown',
            labels: labels
          });
        }
      }
      
      return containers;
    } catch (error) {
      // If lxc-ls fails, try simple listing
      try {
        const { stdout } = await execAsync('lxc-ls');
        const containerNames = stdout.trim().split(/\s+/).filter(name => name.startsWith('cf-'));
        return containerNames.map(name => ({
          id: name,
          name: name,
          image: 'ubuntu:22.04',
          status: 'unknown',
          created: 'unknown',
          labels: {}
        }));
      } catch (fallbackError) {
        throw new Error(`Failed to list LXC containers: ${error.message}`);
      }
    }
  }

  async getInfo(id) {
    try {
      const { stdout } = await execAsync(`lxc-info -n ${id}`);
      const lines = stdout.split('\n');
      
      let status = 'unknown';
      for (const line of lines) {
        if (line.startsWith('State:')) {
          status = line.split(':')[1].trim().toLowerCase();
          break;
        }
      }
      
      const labels = await this.getMetadata(id);
      
      return {
        id: id,
        name: id,
        image: 'ubuntu:22.04',
        status: status,
        created: labels['cf-created'] || 'unknown',
        ports: {}, // LXC doesn't expose ports like Docker
        labels: labels
      };
    } catch (error) {
      throw new Error(`Failed to get LXC container info: ${error.message}`);
    }
  }

  async remove(id) {
    try {
      // Stop container first if running
      try {
        await execAsync(`lxc-stop -n ${id}`);
      } catch (e) {
        // Container might already be stopped
      }
      
      // Delete container
      await execAsync(`lxc-destroy -n ${id}`);
    } catch (error) {
      throw new Error(`Failed to remove LXC container: ${error.message}`);
    }
  }

  async getLogs(id, lines = 100) {
    try {
      // LXC doesn't have built-in log viewing like Docker
      // Try to get recent system logs related to the container
      const { stdout } = await execAsync(`journalctl -u lxc@${id} --lines=${lines} --no-pager`);
      return stdout;
    } catch (error) {
      // Fallback to container-specific logs if they exist
      try {
        const { stdout } = await execAsync(`tail -n ${lines} /var/lib/lxc/${id}/console.log`);
        return stdout;
      } catch (fallbackError) {
        return `No logs available for container ${id}`;
      }
    }
  }

  /**
   * Get container metadata from filesystem
   */
  async getMetadata(containerName) {
    const metadataDir = `/var/lib/lxc/${containerName}/cf-metadata`;
    const metadata = {};
    
    try {
      const files = ['user', 'role', 'type', 'created'];
      for (const file of files) {
        try {
          const { stdout } = await execAsync(`cat ${metadataDir}/${file}`);
          metadata[`cf-${file}`] = stdout.trim();
        } catch (e) {
          // File doesn't exist, skip
        }
      }
    } catch (error) {
      // Metadata directory doesn't exist
    }
    
    return metadata;
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
        await execAsync(`lxc-attach -n ${containerName} -- ${cmd}`);
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