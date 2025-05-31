/**
 * Hot Container Pre-creation System
 * 
 * Pre-creates containers with popular templates for instant provisioning.
 * Maintains a pool of ready-to-use containers to reduce wait times.
 */

const backendManager = require('./backend-manager');
const { getTemplate } = require('./templates');

class HotContainerManager {
    constructor() {
        this.hotContainers = new Map(); // template -> container pool
        this.poolSizes = {
            'ubuntu': 2,
            'python': 2, 
            'node': 2,
            'alpine': 1
        };
        this.cleanupInterval = null;
        this.restockInterval = null;
    }

    /**
     * Initialize hot container system
     */
    async initialize() {
        console.log('🔥 Initializing hot container pools...');
        
        // Pre-create containers for popular templates
        for (const [template, poolSize] of Object.entries(this.poolSizes)) {
            await this.ensurePoolSize(template, poolSize);
        }

        // Start maintenance intervals
        this.startMaintenance();
        
        console.log('✅ Hot container system initialized');
    }

    /**
     * Get a hot container for immediate use
     */
    async getHotContainer(templateName, userId, username, userRole) {
        const pool = this.hotContainers.get(templateName) || [];
        
        if (pool.length > 0) {
            const container = pool.pop();
            this.hotContainers.set(templateName, pool);
            
            console.log(`🚀 Using hot container ${container.id} for template ${templateName}`);
            
            // Configure container for user
            await this.configureContainerForUser(container, userId, username, userRole);
            
            // Async restock (don't wait)
            this.restockPool(templateName);
            
            return container;
        }

        return null; // No hot containers available
    }

    /**
     * Ensure pool has minimum number of containers
     */
    async ensurePoolSize(templateName, targetSize) {
        const pool = this.hotContainers.get(templateName) || [];
        const needed = targetSize - pool.length;
        
        if (needed > 0) {
            console.log(`📦 Creating ${needed} hot containers for ${templateName}`);
            
            for (let i = 0; i < needed; i++) {
                try {
                    const container = await this.createHotContainer(templateName);
                    if (container) {
                        pool.push(container);
                    }
                } catch (error) {
                    console.error(`Failed to create hot container for ${templateName}:`, error.message);
                }
            }
            
            this.hotContainers.set(templateName, pool);
        }
    }

    /**
     * Create a pre-configured container
     */
    async createHotContainer(templateName) {
        const template = getTemplate(templateName);
        if (!template) {
            throw new Error(`Unknown template: ${templateName}`);
        }

        const config = {
            image: template.image,
            workdir: template.workdir || '/workspace',
            env: template.env || [],
            volumes: template.volumes || [],
            ports: template.ports || {},
            maxMemory: template.defaultMemory || 512,
            init: template.init || [],
            
            // Hot container specific config
            userId: 'hot-pool',
            username: 'hot-pool',
            userRole: 'system',
            template: templateName,
            isHotContainer: true,
            ttl: 86400 // 24 hours for hot containers
        };

        const backend = backendManager.getDefaultBackend();
        const container = await backend.create(config);
        
        return {
            id: container.id,
            name: container.name,
            template: templateName,
            createdAt: new Date(),
            status: 'ready'
        };
    }

    /**
     * Configure hot container for specific user
     */
    async configureContainerForUser(container, userId, username, userRole) {
        const backend = backendManager.getDefaultBackend();
        
        try {
            // Update container labels for user ownership
            await backend.exec(container.id, `echo "Container assigned to user: ${username}" > /tmp/user-info`);
            
            // Set user-specific environment if needed
            const userCommands = [
                `echo "export USER=${username}" >> /etc/profile`,
                `echo "export USER_ID=${userId}" >> /etc/profile`,
                `echo "export USER_ROLE=${userRole}" >> /etc/profile`
            ];
            
            for (const cmd of userCommands) {
                await backend.exec(container.id, cmd);
            }
            
            console.log(`🔧 Configured container ${container.id} for user ${username}`);
        } catch (error) {
            console.error(`Failed to configure container for user:`, error.message);
        }
    }

    /**
     * Restock pool asynchronously
     */
    async restockPool(templateName) {
        const targetSize = this.poolSizes[templateName] || 1;
        setTimeout(async () => {
            await this.ensurePoolSize(templateName, targetSize);
        }, 1000); // Small delay to avoid blocking
    }

    /**
     * Start maintenance tasks
     */
    startMaintenance() {
        // Cleanup old containers every hour
        this.cleanupInterval = setInterval(() => {
            this.cleanupOldContainers();
        }, 3600000); // 1 hour

        // Restock pools every 30 minutes
        this.restockInterval = setInterval(() => {
            this.restockAllPools();
        }, 1800000); // 30 minutes
    }

    /**
     * Clean up old hot containers
     */
    async cleanupOldContainers() {
        console.log('🧹 Cleaning up old hot containers...');
        
        for (const [template, pool] of this.hotContainers.entries()) {
            const cutoff = new Date(Date.now() - 86400000); // 24 hours ago
            const fresh = [];
            const stale = [];
            
            pool.forEach(container => {
                if (container.createdAt > cutoff) {
                    fresh.push(container);
                } else {
                    stale.push(container);
                }
            });
            
            // Remove stale containers
            for (const container of stale) {
                try {
                    const backend = backendManager.getDefaultBackend();
                    await backend.delete(container.id);
                    console.log(`🗑️ Removed stale hot container: ${container.id}`);
                } catch (error) {
                    console.error(`Failed to remove stale container ${container.id}:`, error.message);
                }
            }
            
            this.hotContainers.set(template, fresh);
        }
    }

    /**
     * Restock all pools
     */
    async restockAllPools() {
        console.log('🔄 Restocking hot container pools...');
        
        for (const [template, targetSize] of Object.entries(this.poolSizes)) {
            await this.ensurePoolSize(template, targetSize);
        }
    }

    /**
     * Get pool status
     */
    getPoolStatus() {
        const status = {};
        
        for (const [template, targetSize] of Object.entries(this.poolSizes)) {
            const pool = this.hotContainers.get(template) || [];
            status[template] = {
                target: targetSize,
                available: pool.length,
                containers: pool.map(c => ({
                    id: c.id,
                    createdAt: c.createdAt,
                    age: Math.floor((Date.now() - c.createdAt.getTime()) / 1000)
                }))
            };
        }
        
        return status;
    }

    /**
     * Update pool sizes
     */
    updatePoolSizes(newSizes) {
        Object.assign(this.poolSizes, newSizes);
        console.log('Updated pool sizes:', this.poolSizes);
    }

    /**
     * Shutdown and cleanup
     */
    async shutdown() {
        if (this.cleanupInterval) clearInterval(this.cleanupInterval);
        if (this.restockInterval) clearInterval(this.restockInterval);
        
        console.log('🛑 Hot container system shutdown');
    }
}

// Export singleton instance
module.exports = new HotContainerManager();