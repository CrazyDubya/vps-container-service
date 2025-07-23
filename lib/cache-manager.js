/**
 * Redis Cache Manager
 * 
 * Provides caching functionality for container listings, user data,
 * and frequently accessed information to improve performance.
 */

const redis = require('redis');

class CacheManager {
    constructor() {
        this.client = null;
        this.connected = false;
        this.defaultTTL = 300; // 5 minutes default
    }

    /**
     * Initialize Redis connection
     */
    async initialize() {
        // Skip Redis if explicitly disabled
        if (process.env.REDIS_ENABLED === 'false') {
            console.log('📦 Redis caching disabled via environment');
            this.connected = false;
            return;
        }
        
        const redisUrl = process.env.REDIS_URL || 'redis://localhost:6379';
        
        try {
            this.client = redis.createClient({
                url: redisUrl,
                retry_strategy: (options) => {
                    if (options.error && options.error.code === 'ECONNREFUSED') {
                        console.warn('Redis connection refused, running without cache');
                        return undefined; // Don't retry
                    }
                    if (options.total_retry_time > 1000 * 60 * 60) {
                        return new Error('Retry time exhausted');
                    }
                    if (options.attempt > 3) {
                        return undefined;
                    }
                    return Math.min(options.attempt * 100, 3000);
                }
            });

            this.client.on('error', (err) => {
                console.warn('Redis error:', err.message);
                this.connected = false;
            });

            this.client.on('connect', () => {
                console.log('📦 Redis cache connected');
                this.connected = true;
            });

            this.client.on('end', () => {
                console.log('📦 Redis cache disconnected');
                this.connected = false;
            });

            await this.client.connect();
        } catch (error) {
            console.warn('Redis unavailable, running without cache:', error.message);
            this.connected = false;
        }
    }

    /**
     * Get value from cache
     */
    async get(key) {
        if (!this.connected || !this.client) return null;
        
        try {
            const value = await this.client.get(key);
            return value ? JSON.parse(value) : null;
        } catch (error) {
            console.warn('Cache get error:', error.message);
            return null;
        }
    }

    /**
     * Set value in cache
     */
    async set(key, value, ttl = this.defaultTTL) {
        if (!this.connected || !this.client) return false;
        
        try {
            await this.client.setEx(key, ttl, JSON.stringify(value));
            return true;
        } catch (error) {
            console.warn('Cache set error:', error.message);
            return false;
        }
    }

    /**
     * Delete key from cache
     */
    async del(key) {
        if (!this.connected || !this.client) return false;
        
        try {
            await this.client.del(key);
            return true;
        } catch (error) {
            console.warn('Cache delete error:', error.message);
            return false;
        }
    }

    /**
     * Cache with automatic refresh
     */
    async getOrSet(key, fetchFunction, ttl = this.defaultTTL) {
        // Try to get from cache first
        let value = await this.get(key);
        
        if (value === null) {
            // Not in cache, fetch fresh data
            try {
                value = await fetchFunction();
                await this.set(key, value, ttl);
            } catch (error) {
                console.error('Cache fetch function error:', error);
                throw error;
            }
        }
        
        return value;
    }

    /**
     * Cache container listing
     */
    async cacheContainerList(userId, containers) {
        const key = `containers:${userId}`;
        await this.set(key, containers, 60); // 1 minute TTL for dynamic data
    }

    /**
     * Get cached container listing
     */
    async getCachedContainerList(userId) {
        const key = `containers:${userId}`;
        return await this.get(key);
    }

    /**
     * Cache user profile data
     */
    async cacheUserProfile(userId, profile) {
        const key = `user:${userId}`;
        await this.set(key, profile, 1800); // 30 minutes TTL
    }

    /**
     * Get cached user profile
     */
    async getCachedUserProfile(userId) {
        const key = `user:${userId}`;
        return await this.get(key);
    }

    /**
     * Cache template data
     */
    async cacheTemplates(templates) {
        await this.set('templates:all', templates, 3600); // 1 hour TTL
    }

    /**
     * Get cached templates
     */
    async getCachedTemplates() {
        return await this.get('templates:all');
    }

    /**
     * Cache container stats
     */
    async cacheContainerStats(containerId, stats) {
        const key = `stats:${containerId}`;
        await this.set(key, stats, 30); // 30 seconds TTL for stats
    }

    /**
     * Get cached container stats
     */
    async getCachedContainerStats(containerId) {
        const key = `stats:${containerId}`;
        return await this.get(key);
    }

    /**
     * Invalidate user-related caches
     */
    async invalidateUserCache(userId) {
        await this.del(`user:${userId}`);
        await this.del(`containers:${userId}`);
    }

    /**
     * Invalidate container-related caches
     */
    async invalidateContainerCache(containerId, userId = null) {
        await this.del(`stats:${containerId}`);
        if (userId) {
            await this.del(`containers:${userId}`);
        }
    }

    /**
     * Get cache statistics
     */
    async getStats() {
        if (!this.connected || !this.client) {
            return { connected: false, status: 'unavailable' };
        }

        try {
            const info = await this.client.info('memory');
            const keyspace = await this.client.info('keyspace');
            
            return {
                connected: this.connected,
                status: 'active',
                memory: this.parseRedisInfo(info),
                keyspace: this.parseRedisInfo(keyspace)
            };
        } catch (error) {
            return { connected: false, status: 'error', error: error.message };
        }
    }

    /**
     * Parse Redis INFO output
     */
    parseRedisInfo(info) {
        const lines = info.split('\r\n');
        const result = {};
        
        lines.forEach(line => {
            if (line.includes(':')) {
                const [key, value] = line.split(':');
                result[key] = value;
            }
        });
        
        return result;
    }

    /**
     * Flush all cache data
     */
    async flush() {
        if (!this.connected || !this.client) return false;
        
        try {
            await this.client.flushAll();
            console.log('Cache flushed');
            return true;
        } catch (error) {
            console.warn('Cache flush error:', error.message);
            return false;
        }
    }

    /**
     * Close connection
     */
    async close() {
        if (this.client) {
            await this.client.quit();
            this.connected = false;
        }
    }

    /**
     * Check if cache is available
     */
    isAvailable() {
        return this.connected;
    }
}

// Export singleton instance
module.exports = new CacheManager();