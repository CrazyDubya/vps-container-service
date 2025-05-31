/**
 * Centralized Backend Manager
 * 
 * Manages backend instances and provides consistent interface
 * across all service endpoints.
 */

const BackendFactory = require('./backend-factory');

class BackendManager {
    constructor() {
        this.backends = new Map();
        this.defaultBackend = process.env.BACKEND_TYPE || 'lxd';
    }

    /**
     * Get backend instance (cached)
     */
    getBackend(type = null) {
        const backendType = type || this.defaultBackend;
        
        if (!this.backends.has(backendType)) {
            this.backends.set(backendType, BackendFactory.create(backendType));
        }
        
        return this.backends.get(backendType);
    }

    /**
     * Get default backend
     */
    getDefaultBackend() {
        return this.getBackend();
    }

    /**
     * List containers across all backends or specific backend
     */
    async listContainers(backendType = null) {
        const backend = this.getBackend(backendType);
        return await backend.list();
    }

    /**
     * Create container using default backend
     */
    async createContainer(config) {
        const backend = this.getDefaultBackend();
        return await backend.create(config);
    }

    /**
     * Get container info (auto-detect backend if needed)
     */
    async getContainer(containerId, backendType = null) {
        if (backendType) {
            const backend = this.getBackend(backendType);
            return await backend.inspect(containerId);
        }

        // Try to find container across backends
        for (const [type, backend] of this.backends) {
            try {
                return await backend.inspect(containerId);
            } catch (error) {
                // Container not found in this backend, try next
                continue;
            }
        }

        // Try default backend if not already tried
        if (!this.backends.has(this.defaultBackend)) {
            const backend = this.getDefaultBackend();
            return await backend.inspect(containerId);
        }

        throw new Error(`Container ${containerId} not found in any backend`);
    }

    /**
     * Stop container
     */
    async stopContainer(containerId, backendType = null) {
        const backend = this.getBackend(backendType);
        return await backend.stop(containerId);
    }

    /**
     * Delete container
     */
    async deleteContainer(containerId, backendType = null) {
        const backend = this.getBackend(backendType);
        return await backend.delete(containerId);
    }

    /**
     * Execute command in container
     */
    async execInContainer(containerId, command, backendType = null) {
        const backend = this.getBackend(backendType);
        return await backend.exec(containerId, command);
    }

    /**
     * Get container logs
     */
    async getContainerLogs(containerId, lines = 100, backendType = null) {
        const backend = this.getBackend(backendType);
        return await backend.logs(containerId, lines);
    }

    /**
     * Get container stats
     */
    async getContainerStats(containerId, backendType = null) {
        const backend = this.getBackend(backendType);
        return await backend.stats(containerId);
    }

    /**
     * Copy file to container
     */
    async copyToContainer(containerId, sourcePath, targetPath, backendType = null) {
        const backend = this.getBackend(backendType);
        return await backend.copyTo(containerId, sourcePath, targetPath);
    }

    /**
     * Copy file from container
     */
    async copyFromContainer(containerId, sourcePath, targetPath, backendType = null) {
        const backend = this.getBackend(backendType);
        return await backend.copyFrom(containerId, sourcePath, targetPath);
    }

    /**
     * Attach interactive terminal
     */
    async attachTerminal(containerId, backendType = null) {
        const backend = this.getBackend(backendType);
        return await backend.attachInteractive(containerId);
    }

    /**
     * Get available backends
     */
    getAvailableBackends() {
        return BackendFactory.getAvailableBackends();
    }

    /**
     * Get current default backend type
     */
    getDefaultBackendType() {
        return this.defaultBackend;
    }

    /**
     * Clear backend cache (for testing/debugging)
     */
    clearCache() {
        this.backends.clear();
    }
}

// Export singleton instance
module.exports = new BackendManager();