'use strict';

function createRateLimiter({ windowMs, max, keyFn, message = 'Too many requests' }) {
    const buckets = new Map();

    return (req, res, next) => {
        const now = Date.now();
        const key = String(keyFn ? keyFn(req) : req.ip || req.socket.remoteAddress || 'unknown');
        let bucket = buckets.get(key);

        if (!bucket || bucket.resetAt <= now) {
            bucket = { count: 0, resetAt: now + windowMs };
            buckets.set(key, bucket);
        }

        bucket.count += 1;
        if (bucket.count > max) {
            const retryAfter = Math.max(1, Math.ceil((bucket.resetAt - now) / 1000));
            res.set('Retry-After', String(retryAfter));
            return res.status(429).json({ error: message });
        }

        // Opportunistic pruning avoids an unbounded map without a background timer.
        if (buckets.size > 5000) {
            for (const [bucketKey, value] of buckets) {
                if (value.resetAt <= now) buckets.delete(bucketKey);
                if (buckets.size <= 4000) break;
            }
        }

        next();
    };
}

module.exports = { createRateLimiter };
