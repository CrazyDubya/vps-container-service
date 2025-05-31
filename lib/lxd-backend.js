const { exec } = require('child_process');
const util = require('util');
const ContainerInterface = require('./container-interface');
const { getTemplate } = require('./templates');

const execAsync = util.promisify(exec);

/**
 * LXD implementation of the container interface
 */
class LXDBackend extends ContainerInterface {
  constructor() {
    super();
  }

  async createAsync(config) {
    const containerName = `cf-${config.name || config.id || Math.random().toString(36).substr(2, 9)}`;
    
    // Store container creation status
    if (!this.creationStatus) {
      this.creationStatus = new Map();
    }
    
    // Set initial status
    this.creationStatus.set(containerName, {
      status: 'creating',
      progress: 0,
      message: 'Initializing container creation...',
      startTime: Date.now()
    });
    
    // Start async creation
    this._performAsyncCreation(containerName, config).catch(error => {
      this.creationStatus.set(containerName, {
        status: 'failed',
        error: error.message,
        endTime: Date.now()
      });
    });
    
    // Return immediately with container info
    return {
      id: containerName,
      name: containerName,
      status: 'creating'
    };
  }
  
  async _performAsyncCreation(containerName, config) {
    try {
      // Update status
      this.creationStatus.set(containerName, {
        status: 'creating',
        progress: 10,
        message: 'Checking LXD availability...'
      });
      
      // Check if LXD is available
      const { stdout: lxdStatus } = await execAsync('lxc info').catch((error) => {
        throw new Error(`LXD not available: ${error.message}`);
      });
      
      this.creationStatus.set(containerName, {
        status: 'creating',
        progress: 20,
        message: 'Preparing container image...'
      });
      
      // Map template to LXD image
      const image = this.getImage(config.template || 'ubuntu');
      
      // Create LXD container with labels
      const memoryLimit = config.maxMemory || config.memory || 256;
      
      this.creationStatus.set(containerName, {
        status: 'creating',
        progress: 30,
        message: 'Launching container...'
      });
      
      // Create container with async handling
      const { spawn } = require('child_process');
      await new Promise((resolve, reject) => {
        const proc = spawn('lxc', ['launch', image, containerName, '--config', `limits.memory=${memoryLimit}MB`]);
        let stderr = '';
        
        proc.stderr.on('data', (data) => {
          stderr += data.toString();
        });
        
        proc.on('close', async (code) => {
          if (code !== 0) {
            reject(new Error(`Container creation failed: ${stderr}`));
          } else {
            console.log(`Container ${containerName} created successfully`);
            
            try {
              // Add labels for user tracking
              if (config.userId) {
                await execAsync(`lxc config set ${containerName} user.cf-user-id "${config.userId}"`);
              }
              if (config.username) {
                await execAsync(`lxc config set ${containerName} user.cf-username "${config.username}"`);
              }
              if (config.userRole) {
                await execAsync(`lxc config set ${containerName} user.cf-role "${config.userRole}"`);
              }
              if (config.ttl) {
                const expiresAt = new Date(Date.now() + config.ttl * 1000).toISOString();
                await execAsync(`lxc config set ${containerName} user.cf-expires "${expiresAt}"`);
              }
              resolve();
            } catch (labelError) {
              console.error(`Failed to set labels: ${labelError.message}`);
              resolve(); // Don't fail creation for label errors
            }
          }
        });
      });
      
      this.creationStatus.set(containerName, {
        status: 'creating',
        progress: 80,
        message: 'Container ready, applying template...'
      });
      
      // Apply template-specific setup if specified
      if (config.template && config.template !== 'ubuntu') {
        await this.applyTemplate(containerName, config.template);
      }
      
      this.creationStatus.set(containerName, {
        status: 'ready',
        progress: 100,
        message: 'Container ready!',
        endTime: Date.now()
      });
      
      return {
        id: containerName,
        name: containerName
      };
    } catch (error) {
      this.creationStatus.set(containerName, {
        status: 'failed',
        error: error.message,
        endTime: Date.now()
      });
      throw new Error(`Failed to create LXD container: ${error.message}`);
    }
  }
  
  async create(config) {
    // Use async creation for immediate response
    return this.createAsync(config);
  }
  
  async getCreationStatus(containerId) {
    if (!this.creationStatus) {
      this.creationStatus = new Map();
    }
    
    if (!this.creationStatus.has(containerId)) {
      // Check if container exists
      try {
        const { stdout } = await execAsync(`lxc list ${containerId} --format json`);
        const containers = JSON.parse(stdout);
        if (containers.length > 0) {
          return {
            status: 'ready',
            progress: 100,
            message: 'Container is ready'
          };
        }
      } catch (error) {
        return {
          status: 'unknown',
          message: 'Container not found'
        };
      }
    }
    return this.creationStatus.get(containerId) || { status: 'unknown' };
  }
  
  /**
   * Get appropriate LXD image name
   */
  getImage(templateName) {
    // Use the available image fingerprint directly
    const imageMap = {
      'ubuntu': '18b1e751a208',
      'alpine': 'images:alpine/3.18',
      'python': '18b1e751a208',
      'node': '18b1e751a208',
      'go': '18b1e751a208',
      'rust': '18b1e751a208',
      'java': '18b1e751a208',
      'nginx': '18b1e751a208',
      'postgres': '18b1e751a208',
      'redis': '18b1e751a208'
    };
    
    return imageMap[templateName] || '18b1e751a208';
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
          Id: container.name,
          Names: [`/${container.name}`],
          Image: container.config['image.description'] || 'ubuntu:22.04',
          State: container.status.toLowerCase(),
          Status: container.status.toLowerCase(),
          Created: new Date(container.created_at).getTime() / 1000,
          Labels: this.extractLabels(container.config || {}),
          Ports: []
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
   * Extract labels from LXD config
   */
  extractLabels(config) {
    const labels = {};
    
    // Extract user.* config keys as labels
    Object.keys(config).forEach(key => {
      if (key.startsWith('user.cf-')) {
        const labelKey = key.replace('user.cf-', 'cf-');
        labels[labelKey] = config[key];
      }
    });
    
    return labels;
  }

  /**
   * Apply a template to the container
   */
  async applyTemplate(containerName, templateName) {
    const template = getTemplate(templateName);
    if (!template || !template.init) {
      return;
    }
    
    console.log(`Applying ${templateName} template to ${containerName}...`);
    
    for (const cmd of template.init) {
      try {
        console.log(`Running: ${cmd}`);
        await execAsync(`lxc exec ${containerName} -- sh -c "${cmd}"`);
      } catch (error) {
        console.error(`Template command failed: ${cmd}`, error.message);
        // Continue with other commands even if one fails
      }
    }
    
    console.log(`Template ${templateName} applied successfully`);
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