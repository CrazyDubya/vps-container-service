/**
 * Abstract base class for container backends
 * Defines the common interface for both Docker and LXC implementations
 */
class ContainerInterface {
  /**
   * Create a new container
   * @param {Object} config - Container configuration
   * @param {string} config.id - Unique container identifier
   * @param {string} config.image - Base image/template to use
   * @param {string} config.userId - User who owns the container
   * @param {string} config.userRole - User role (user, admin, etc.)
   * @param {number} config.maxMemory - Maximum memory in MB
   * @param {number} config.maxCpu - Maximum CPU usage (0-1)
   * @param {string[]} config.env - Environment variables
   * @param {string[]} config.cmd - Command to run
   * @param {boolean} config.persistent - Whether container should persist
   * @param {string} config.template - Template to apply (optional)
   * @returns {Promise<string>} Container ID
   */
  async create(config) {
    throw new Error('create() method must be implemented by subclass');
  }

  /**
   * Start a container
   * @param {string} id - Container ID
   * @returns {Promise<void>}
   */
  async start(id) {
    throw new Error('start() method must be implemented by subclass');
  }

  /**
   * Stop a container
   * @param {string} id - Container ID
   * @returns {Promise<void>}
   */
  async stop(id) {
    throw new Error('stop() method must be implemented by subclass');
  }

  /**
   * Execute a command in a container
   * @param {string} id - Container ID
   * @param {string} command - Command to execute
   * @returns {Promise<Object>} { output: string, exitCode: number }
   */
  async exec(id, command) {
    throw new Error('exec() method must be implemented by subclass');
  }

  /**
   * List all containers
   * @returns {Promise<Array>} Array of container objects
   */
  async list() {
    throw new Error('list() method must be implemented by subclass');
  }

  /**
   * Get container information
   * @param {string} id - Container ID
   * @returns {Promise<Object>} Container information
   */
  async getInfo(id) {
    throw new Error('getInfo() method must be implemented by subclass');
  }

  /**
   * Remove a container
   * @param {string} id - Container ID
   * @returns {Promise<void>}
   */
  async remove(id) {
    throw new Error('remove() method must be implemented by subclass');
  }

  /**
   * Get container logs
   * @param {string} id - Container ID
   * @param {number} lines - Number of lines to return (default: 100)
   * @returns {Promise<string>} Container logs
   */
  async getLogs(id, lines = 100) {
    throw new Error('getLogs() method must be implemented by subclass');
  }

  /**
   * Get backend type
   * @returns {string} Backend type ('docker' or 'lxc')
   */
  getBackendType() {
    throw new Error('getBackendType() method must be implemented by subclass');
  }
}

module.exports = ContainerInterface;