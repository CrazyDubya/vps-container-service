/**
 * Centralized Error Handling
 */

class ContainerServiceError extends Error {
    constructor(message, code = 'UNKNOWN_ERROR', statusCode = 500) {
        super(message);
        this.name = 'ContainerServiceError';
        this.code = code;
        this.statusCode = statusCode;
    }
}

class ValidationError extends ContainerServiceError {
    constructor(message, field = null) {
        super(message, 'VALIDATION_ERROR', 400);
        this.field = field;
    }
}

class AuthenticationError extends ContainerServiceError {
    constructor(message = 'Authentication failed') {
        super(message, 'AUTH_ERROR', 401);
    }
}

class AuthorizationError extends ContainerServiceError {
    constructor(message = 'Access denied') {
        super(message, 'AUTHORIZATION_ERROR', 403);
    }
}

class NotFoundError extends ContainerServiceError {
    constructor(resource = 'Resource') {
        super(`${resource} not found`, 'NOT_FOUND', 404);
    }
}

class LimitExceededError extends ContainerServiceError {
    constructor(message, limit = null, current = null) {
        super(message, 'LIMIT_EXCEEDED', 429);
        this.limit = limit;
        this.current = current;
    }
}

class BackendError extends ContainerServiceError {
    constructor(message, backend = 'unknown') {
        super(message, 'BACKEND_ERROR', 500);
        this.backend = backend;
    }
}

/**
 * Express error handler middleware
 */
function errorHandler(err, req, res, next) {
    // Log error for debugging
    console.error('Error:', {
        message: err.message,
        code: err.code,
        stack: process.env.NODE_ENV === 'development' ? err.stack : undefined,
        url: req.url,
        method: req.method,
        user: req.user?.username || 'anonymous'
    });

    // Handle known error types
    if (err instanceof ContainerServiceError) {
        return res.status(err.statusCode).json({
            error: err.message,
            code: err.code,
            ...(err.field && { field: err.field }),
            ...(err.limit && { limit: err.limit, current: err.current })
        });
    }

    // Handle validation errors from express-validator
    if (err.name === 'ValidationError') {
        return res.status(400).json({
            error: 'Validation failed',
            code: 'VALIDATION_ERROR',
            details: err.details || err.message
        });
    }

    // Handle JWT errors
    if (err.name === 'JsonWebTokenError') {
        return res.status(401).json({
            error: 'Invalid token',
            code: 'INVALID_TOKEN'
        });
    }

    if (err.name === 'TokenExpiredError') {
        return res.status(401).json({
            error: 'Token expired',
            code: 'TOKEN_EXPIRED'
        });
    }

    // Handle database errors
    if (err.code === 'SQLITE_CONSTRAINT') {
        return res.status(409).json({
            error: 'Resource already exists',
            code: 'DUPLICATE_RESOURCE'
        });
    }

    // Default error response
    res.status(500).json({
        error: process.env.NODE_ENV === 'development' ? err.message : 'Internal server error',
        code: 'INTERNAL_ERROR'
    });
}

/**
 * Async route wrapper to catch errors
 */
function asyncHandler(fn) {
    return (req, res, next) => {
        Promise.resolve(fn(req, res, next)).catch(next);
    };
}

/**
 * Validate required fields
 */
function validateRequired(obj, fields) {
    const missing = fields.filter(field => !obj[field]);
    if (missing.length > 0) {
        throw new ValidationError(`Missing required fields: ${missing.join(', ')}`);
    }
}

/**
 * Validate container ownership
 */
function validateOwnership(container, user, action = 'access') {
    if (user.role === 'admin') {
        return true; // Admins can access everything
    }
    
    const labels = container.Labels || container.labels || {};
    const isOwner = labels['cf-user-id'] === user.id.toString();
    
    if (!isOwner) {
        throw new AuthorizationError(`Cannot ${action} container - access denied`);
    }
    
    return true;
}

/**
 * Validate container limits
 */
function validateContainerLimit(userContainerCount, maxContainers, username) {
    if (userContainerCount >= maxContainers) {
        throw new LimitExceededError(
            `Container limit reached for user ${username}`,
            maxContainers,
            userContainerCount
        );
    }
}

module.exports = {
    // Error classes
    ContainerServiceError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    LimitExceededError,
    BackendError,
    
    // Middleware and utilities
    errorHandler,
    asyncHandler,
    validateRequired,
    validateOwnership,
    validateContainerLimit
};