const { exec, spawn } = require('child_process');
const util = require('util');
const pty = require('node-pty');
const path = require('path');
const fs = require('fs').promises; // For reading cgroup files
const ContainerInterface = require('./container-interface');

const execAsync = util.promisify(exec);

/**
 * LXC implementation of the container interface
 */
class LXCBackend extends ContainerInterface {
  constructor() {
    super();
  }

  /**
   * Validates an LXC container ID or name.
   * @param {string} id The ID to validate.
   * @returns {boolean} True if valid, false otherwise.
   */
  _isValidLxcId(id) {
    if (typeof id !== 'string') return false;
    if (id.length < 3 || id.length > 63) return false;
    if (!/^[a-zA-Z0-9-]+$/.test(id)) return false; // Alphanumeric and hyphens
    if (id.startsWith('-') || id.endsWith('-')) return false; // No leading/trailing hyphens
    if (id.includes('--')) return false; // No consecutive hyphens
    return true;
  }

  /**
   * Validates a template name.
   * @param {string} name The template name to validate.
   * @returns {boolean} True if valid, false otherwise.
   */
  _isValidTemplateName(name) {
    if (typeof name !== 'string') return false;
    if (name.length === 0 || name.length > 50) return false; // Basic length check
    return /^[a-zA-Z0-9_.-]+$/.test(name); // Alphanumeric, underscore, dot, hyphen
  }

  async create(config) {
    if (!config.id || !this._isValidLxcId(`cf-${config.id}`)) {
      throw new Error("Invalid container ID format provided in config.id");
    }
    const containerName = `cf-${config.id}`;

    if (config.template && !this._isValidTemplateName(config.template)) {
      throw new Error("Invalid template name format provided in config.template");
    }
    
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
      
      // Store userId if provided in config
      if (config.userId) {
        // Ensure userId is a simple string or number before writing to prevent injection
        const userIdStr = String(config.userId);
        if (!/^[a-zA-Z0-9_.-]+$/.test(userIdStr)) {
            throw new Error("Invalid characters in userId for metadata storage.");
        }
        await execAsync(`echo "${userIdStr}" > ${metadataDir}/userId`);
      }
      // Remove userRole storage from container metadata
      // await execAsync(`echo "${config.userRole}" > ${metadataDir}/role`); 
      
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
    if (!this._isValidLxcId(id)) {
      throw new Error("Invalid container ID format for start operation.");
    }
    try {
      await execAsync(`lxc-start -n ${id} -d`);
    } catch (error) {
      throw new Error(`Failed to start LXC container: ${error.message}`);
    }
  }

  async stop(id) {
    if (!this._isValidLxcId(id)) {
      throw new Error("Invalid container ID format for stop operation.");
    }
    try {
      await execAsync(`lxc-stop -n ${id}`);
    } catch (error) {
      throw new Error(`Failed to stop LXC container: ${error.message}`);
    }
  }

  async exec(id, command) {
    if (!this._isValidLxcId(id)) {
      throw new Error("Invalid container ID format for exec operation.");
    }
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

  async list(userId = null) {
    try {
      const { stdout } = await execAsync('lxc-ls -f');
      const lines = stdout.trim().split('\n');
      
      if (lines.length <= 1) return []; // No containers or just header
      
      const processedContainers = [];
      for (let i = 1; i < lines.length; i++) { // Skip header
        const parts = lines[i].trim().split(/\s+/);
        if (parts.length >= 2 && parts[0].startsWith('cf-')) {
          const name = parts[0];
          const status = parts[1];
          
          const labels = await this.getMetadata(name);
          
          if (userId !== null) {
            // If userId is provided, filter by it.
            // Ensure userId is compared as a string, as metadata values are strings.
            if (labels['cf-userId'] === String(userId)) {
              processedContainers.push({
                id: name,
                name: name,
                image: 'ubuntu:22.04', // LXC doesn't track original image
                status: status.toLowerCase(),
                created: labels['cf-created'] || 'unknown',
                labels: labels
              });
            }
          } else {
            // If no userId is provided (admin case), include all cf- containers.
            processedContainers.push({
              id: name,
              name: name,
              image: 'ubuntu:22.04',
              status: status.toLowerCase(),
              created: labels['cf-created'] || 'unknown',
              labels: labels
            });
          }
        }
      }
      return processedContainers;

    } catch (error) {
      // If lxc-ls -f fails, try a simpler listing and then filter if needed.
      // This fallback is less efficient for filtering by userId as it fetches metadata for all.
      console.warn("lxc-ls -f failed, attempting fallback simple list. Filtering might be slower.", error.message);
      try {
        const { stdout } = await execAsync('lxc-ls');
        const containerNames = stdout.trim().split(/\s+/).filter(name => name.startsWith('cf-'));
        
        const allContainers = [];
        for (const name of containerNames) {
            const labels = await this.getMetadata(name);
            allContainers.push({
              id: name,
              name: name,
              image: 'ubuntu:22.04',
              status: 'unknown', // Simple 'lxc-ls' doesn't provide status
              created: labels['cf-created'] || 'unknown',
              labels: labels
            });
        }

        if (userId !== null) {
          return allContainers.filter(c => c.labels['cf-userId'] === String(userId));
        }
        return allContainers;

      } catch (fallbackError) {
        throw new Error(`Failed to list LXC containers (fallback also failed): ${fallbackError.message}`);
      }
    }
  }

  async getInfo(id) {
    if (!this._isValidLxcId(id)) {
      throw new Error("Invalid container ID format for getInfo operation.");
    }
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
    if (!this._isValidLxcId(id)) {
      throw new Error("Invalid container ID format for remove operation.");
    }
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
    if (!this._isValidLxcId(id)) {
      throw new Error("Invalid container ID format for getLogs operation.");
    }
    // Ensure lines is a number to prevent injection if it were used in a command string directly
    const numLines = parseInt(lines, 10);
    if (isNaN(numLines) || numLines <= 0) {
        throw new Error("Invalid number of lines for logs.");
    }

    try {
      // LXC doesn't have built-in log viewing like Docker
      // Try to get recent system logs related to the container
      // The 'lines' variable is used as a number, so it's safe here.
      const { stdout } = await execAsync(`journalctl -u lxc@${id} --lines=${numLines} --no-pager`);
      return stdout;
    } catch (error) {
      // Fallback to container-specific logs if they exist
      try {
        const { stdout } = await execAsync(`tail -n ${numLines} /var/lib/lxc/${id}/console.log`);
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
    // This is an internal function, assume containerName is already validated by caller
    // If not, add: if (!this._isValidLxcId(containerName)) { throw new Error("Invalid container name for getMetadata"); }
    const metadataDir = `/var/lib/lxc/${containerName}/cf-metadata`;
    const metadata = {};
    
    try {
      // Extended to include 'userId' and map 'user' to 'userId' for consistency if old 'user' file exists
      const filesToRead = [
        {fileName: 'userId', metadataKey: 'cf-userId'}, // New primary key for user ID
        {fileName: 'user', metadataKey: 'cf-user'},     // Old key, keep for backward compatibility if desired, or remove
        {fileName: 'type', metadataKey: 'cf-type'},
        {fileName: 'created', metadataKey: 'cf-created'}
        // 'role' is intentionally omitted as it's not stored on the container
      ];

      for (const item of filesToRead) {
        try {
          const { stdout } = await execAsync(`cat ${metadataDir}/${item.fileName}`);
          metadata[item.metadataKey] = stdout.trim();
        } catch (e) {
          // File doesn't exist, skip
        }
      }
      // If new cf-userId exists, prefer it. If not, but old cf-user exists, map it.
      if (!metadata['cf-userId'] && metadata['cf-user']) {
          metadata['cf-userId'] = metadata['cf-user'];
      }
      // Remove the old cf-user key if cf-userId is now set from it, to avoid confusion
      if (metadata['cf-userId'] && metadata['cf-user'] && metadata['cf-userId'] === metadata['cf-user']){
          delete metadata['cf-user'];
      }


    } catch (error) {
      // Metadata directory doesn't exist or other read error
      console.warn(`Could not read metadata for ${containerName}: ${error.message}`);
    }
    
    return metadata;
  }

  /**
   * Apply a template to the container
   * @param {string} containerName - Container name
   * @param {string} template - Template to apply
   */
  async applyTemplate(containerName, template) {
    if (!this._isValidLxcId(containerName)) {
        throw new Error("Invalid container name format for applyTemplate operation.");
    }
    if (!this._isValidTemplateName(template)) {
        throw new Error("Invalid template name format for applyTemplate operation.");
    }

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

  /**
   * Starts an interactive terminal session for an LXC container.
   * @param {string} containerId - The ID of the LXC container.
   * @param {function} onDataCallback - Callback for when data is received from the terminal.
   * @param {function} onCloseCallback - Callback for when the terminal session closes.
   * @param {object} [options={ rows: 24, cols: 80 }] - Terminal dimensions.
   * @returns {object} - An object with methods to interact with the terminal.
   */
  async startTerminal(containerId, onDataCallback, onCloseCallback, options = { rows: 24, cols: 80 }) {
    if (!this._isValidLxcId(containerId)) {
      throw new Error("Invalid container ID format for startTerminal operation.");
    }

    try {
      const term = pty.spawn('lxc-attach', ['-n', containerId, '--clear-env', '--', '/bin/sh'], {
        name: 'xterm-color',
        cols: options.cols || 80,
        rows: options.rows || 24,
        cwd: process.env.HOME, // Or a more relevant path like '/root' or '/' inside container
        env: process.env,     // Or a minimal environment
        encoding: 'utf8'      // Ensure UTF-8 encoding
      });

      term.onData((data) => { // Use onData as per node-pty docs
        if (onDataCallback) {
          onDataCallback(data);
        }
      });

      term.onExit(({ exitCode, signal }) => { // Use onExit as per node-pty docs
        if (onCloseCallback) {
          onCloseCallback({ exitCode, signal });
        }
      });
      
      // Add an error handler for the pty process itself
      term.on('error', (err) => {
        console.error(`PTY process error for container ${containerId}:`, err);
        // Potentially call onCloseCallback here as well, depending on desired behavior
        if (onCloseCallback) {
            onCloseCallback({ error: err });
        }
      });

      return {
        writeData: (data) => {
          term.write(data);
        },
        resize: (cols, rows) => {
          if (cols > 0 && rows > 0) { // Add basic validation for cols and rows
            term.resize(cols, rows);
          }
        },
        kill: () => {
          term.kill();
        }
      };
    } catch (error) {
      console.error(`Failed to spawn PTY for LXC container ${containerId}:`, error);
      throw new Error(`Failed to start terminal for LXC container ${containerId}: ${error.message}`);
    }
  }

  /**
   * Validates if a path is safe for use inside a container (absolute, no traversal).
   * @param {string} filePath The path to validate.
   * @returns {boolean} True if valid, false otherwise.
   */
  _isValidContainerPath(filePath) {
    if (typeof filePath !== 'string' || filePath.length === 0) return false;
    if (!filePath.startsWith('/')) return false; // Must be absolute
    if (filePath.includes('..')) return false; // No directory traversal
    // Further checks can be added, e.g., character whitelist, max length
    return true;
  }

  async pushFile(containerId, targetPathInContainer, fileReadStream) {
    if (!this._isValidLxcId(containerId)) {
      throw new Error("Invalid container ID format for pushFile operation.");
    }
    if (!this._isValidContainerPath(targetPathInContainer)) {
      throw new Error("Invalid target path format for pushFile. Must be an absolute path without '..'.");
    }

    return new Promise((resolve, reject) => {
      const targetDir = path.dirname(targetPathInContainer);
      // Command ensures directory exists, then cats stdin to the file.
      // Using sh -c to handle the compound command.
      const command = `mkdir -p "${targetDir}" && cat > "${targetPathInContainer}"`;
      
      const lxcAttachProcess = spawn('lxc-attach', ['-n', containerId, '--clear-env', '--', '/bin/sh', '-c', command]);

      fileReadStream.pipe(lxcAttachProcess.stdin);

      let stderrData = '';
      lxcAttachProcess.stderr.on('data', (data) => {
        stderrData += data.toString();
      });

      lxcAttachProcess.on('error', (err) => {
        reject(new Error(`lxc-attach process failed to spawn for pushFile: ${err.message}`));
      });
      
      fileReadStream.on('error', (err) => {
        lxcAttachProcess.kill(); // Kill lxc-attach if read stream errors
        reject(new Error(`File read stream error during pushFile: ${err.message}`));
      });

      lxcAttachProcess.on('exit', (code) => {
        if (code === 0) {
          resolve();
        } else {
          reject(new Error(`lxc-attach exited with code ${code} during pushFile. Stderr: ${stderrData}`));
        }
      });
    });
  }

  async pullFile(containerId, sourcePathInContainer) {
    if (!this._isValidLxcId(containerId)) {
      // For pullFile, we return a stream, so we need to make the stream emit an error.
      const { PassThrough } = require('stream');
      const errorStream = new PassThrough();
      process.nextTick(() => errorStream.emit('error', new Error("Invalid container ID format for pullFile operation.")));
      return errorStream;
    }
    if (!this._isValidContainerPath(sourcePathInContainer)) {
      const { PassThrough } = require('stream');
      const errorStream = new PassThrough();
      process.nextTick(() => errorStream.emit('error', new Error("Invalid source path format for pullFile. Must be an absolute path without '..'.")));
      return errorStream;
    }

    const lxcAttachProcess = spawn('lxc-attach', ['-n', containerId, '--clear-env', '--', 'cat', sourcePathInContainer]);

    let stderrData = '';
    lxcAttachProcess.stderr.on('data', (data) => {
      stderrData += data.toString();
    });

    lxcAttachProcess.on('error', (err) => {
      lxcAttachProcess.stdout.emit('error', new Error(`lxc-attach process failed to spawn for pullFile: ${err.message}`));
      lxcAttachProcess.stdout.destroy(); // Ensure stream is destroyed
    });
    
    lxcAttachProcess.on('exit', (code) => {
      if (code !== 0) {
        // If cat fails (e.g. file not found), it often prints to stderr and exits non-zero.
        const errorMessage = stderrData || `lxc-attach exited with code ${code} during pullFile.`;
        lxcAttachProcess.stdout.emit('error', new Error(errorMessage));
        lxcAttachProcess.stdout.destroy();
      }
      // If exit code is 0, stdout will end naturally.
    });
    
    // It's important that stdout is returned synchronously for the caller to pipe from.
    return lxcAttachProcess.stdout;
  }

  /**
   * Parses a memory string (e.g., "123.45 MiB") into bytes.
   * @param {string} memString The memory string.
   * @returns {number|null} Memory in bytes or null if parsing fails.
   */
  _parseMemoryToBytes(memString) {
    if (!memString) return null;
    const parts = memString.trim().split(/\s+/);
    if (parts.length !== 2) return null;

    const value = parseFloat(parts[0]);
    const unit = parts[1].toLowerCase();

    if (isNaN(value)) return null;

    switch (unit) {
      case 'kib':
      case 'kb':
        return Math.floor(value * 1024);
      case 'mib':
      case 'mb':
        return Math.floor(value * 1024 * 1024);
      case 'gib':
      case 'gb':
        return Math.floor(value * 1024 * 1024 * 1024);
      case 'tib': // Terabytes, just in case
      case 'tb':
        return Math.floor(value * 1024 * 1024 * 1024 * 1024);
      case 'bytes':
      case 'b':
        return Math.floor(value);
      default:
        return null;
    }
  }

  async getStats(containerId) {
    if (!this._isValidLxcId(containerId)) {
      throw new Error("Invalid container ID format for getStats operation.");
    }

    try {
      const { stdout } = await execAsync(`lxc-info -n ${containerId}`);
      const lines = stdout.split('\n');

      let cpuRaw = "N/A";
      let memoryUsageString = "N/A";
      let diskIORaw = "N/A";

      lines.forEach(line => {
        if (line.startsWith('CPU use:')) {
          cpuRaw = line.split(':')[1].trim();
        } else if (line.startsWith('Memory use:')) {
          memoryUsageString = line.split(':')[1].trim();
        } else if (line.startsWith('BlkIO use:')) {
          diskIORaw = line.split(':')[1].trim();
        }
      });

      const memoryUsageBytes = this._parseMemoryToBytes(memoryUsageString);
      
      let memoryLimitBytes = null;
      try {
        // Attempt to read cgroup memory limit. This might fail if permissions are insufficient
        // or the path structure is different (e.g. cgroup v2).
        const memoryLimitPath = `/sys/fs/cgroup/memory/lxc/${containerId}/memory.limit_in_bytes`;
        const limitContent = await fs.readFile(memoryLimitPath, 'utf8');
        const limitVal = parseInt(limitContent.trim(), 10);
        // Check if it's a very large number, often indicating no limit (or a system-wide one)
        // For practical purposes, if it's larger than, say, 1 petabyte, treat as no limit.
        if (!isNaN(limitVal) && limitVal < Number.MAX_SAFE_INTEGER && limitVal > 0 && limitVal < (1024 * 1024 * 1024 * 1024 * 1024) ) {
          memoryLimitBytes = limitVal;
        }
      } catch (cgroupError) {
        console.warn(`Could not read memory limit for LXC container ${containerId}: ${cgroupError.message}`);
        // It's common for this to fail or for the limit to be effectively "unlimited".
      }
      
      // Network I/O is generally not available directly from lxc-info or simple cgroup files
      // and would require parsing output from `lxc-attach -n NAME -- ip -s link` or similar.
      // For this subtask, it's acceptable to return "N/A".

      return {
        cpuRaw: cpuRaw, // e.g., "123.45s"
        memoryUsageBytes: memoryUsageBytes, // e.g., 129450000 (bytes)
        memoryLimitBytes: memoryLimitBytes, // e.g., 536870912 (bytes) or null
        diskIORaw: diskIORaw, // e.g., "67.89 MiB"
        networkIORaw: "N/A" // LXC Network I/O not implemented in this version
      };

    } catch (error) {
      // Handle cases where lxc-info might fail (e.g., container not running or stopped during query)
      if (error.message && error.message.toLowerCase().includes('is not running')) {
           throw new Error(`Container ${containerId} is not running or not found for stats.`);
      }
      console.error(`Failed to get stats for LXC container ${containerId}:`, error);
      throw new Error(`Failed to retrieve stats for LXC container ${containerId}: ${error.message}`);
    }
  }
}

module.exports = LXCBackend;