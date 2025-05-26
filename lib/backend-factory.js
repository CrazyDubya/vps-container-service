const DockerBackend = require('./docker-backend');
const LXCBackend = require('./lxc-backend');

/**
 * Factory for creating container backend instances
 */
class BackendFactory {
  /**
   * Create a container backend instance
   * @param {string} type - Backend type ('docker' or 'lxc')
   * @returns {ContainerInterface} Backend instance
   */
  static create(type = 'docker') {
    switch(type.toLowerCase()) {
      case 'docker':
        return new DockerBackend();
      case 'lxc':
        return new LXCBackend();
      default:
        throw new Error(`Unknown backend type: ${type}. Supported types: docker, lxc`);
    }
  }

  /**
   * Auto-select backend based on container requirements
   * @param {Object} config - Container configuration
   * @returns {string} Recommended backend type
   */
  static autoSelectBackend(config) {
    // Use LXC for persistent containers or when SSH is needed
    if (config.persistent || config.sshEnabled) {
      return 'lxc';
    }
    
    // Use Docker for quick, ephemeral containers
    return 'docker';
  }

  /**
   * Get available backends
   * @returns {string[]} Array of available backend types
   */
  static getAvailableBackends() {
    return ['docker', 'lxc'];
  }
}

module.exports = BackendFactory;