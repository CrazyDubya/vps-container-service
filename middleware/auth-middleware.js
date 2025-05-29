const jwt = require('jsonwebtoken');
const JWT_SECRET = process.env.JWT_SECRET;
const OperationalError = require('../lib/operational-error'); // Assuming OperationalError is in lib

if (!JWT_SECRET) {
  console.error("CRITICAL: JWT_SECRET is not set in environment for auth-middleware.");
  // This should ideally cause the application to not start,
  // which is handled in container-service.js.
  // However, as a safeguard if this module is loaded independently:
  throw new Error("JWT_SECRET_NOT_CONFIGURED_FOR_AUTH_MIDDLEWARE");
}

/**
 * Middleware to authenticate a JWT token.
 * If valid, attaches user payload to req.user.
 * Otherwise, sends a 401 or 403 error.
 */
const authenticateJWT = (req, res, next) => {
  // If req.user is already set (e.g., by Cloudflare auth), skip local JWT validation
  if (req.user && req.user.authMethod) {
    return next();
  }

  const authHeader = req.headers.authorization;

  if (authHeader) {
    const tokenParts = authHeader.split(' ');
    if (tokenParts.length === 2 && tokenParts[0].toLowerCase() === 'bearer') {
      const token = tokenParts[1];
      jwt.verify(token, JWT_SECRET, (err, userPayload) => {
        if (err) {
          if (err.name === 'TokenExpiredError') {
            return next(new OperationalError('Token expired', 401));
          }
          // For other errors like malformed token, invalid signature
          return next(new OperationalError('Invalid token', 403)); 
        }
        req.user = userPayload; // Add user payload to request object
        next();
      });
    } else {
      // Malformed Authorization header
      return next(new OperationalError('Authorization header is malformed. Expected "Bearer <token>".', 401));
    }
  } else {
    // No Authorization header
    return next(new OperationalError('Access token is required.', 401));
  }
};

/**
 * Middleware factory to authorize users based on roles.
 * @param  {...string} allowedRoles - List of roles allowed to access the route.
 */
const authorizeRoles = (...allowedRoles) => {
  return (req, res, next) => {
    if (!req.user || !req.user.role) {
      // This should ideally not happen if authenticateJWT runs first and is successful
      return next(new OperationalError('Authentication required with role information.', 401));
    }

    if (!allowedRoles.includes(req.user.role)) {
      return next(new OperationalError(`Forbidden: Your role (${req.user.role}) is not authorized to access this resource.`, 403));
    }
    next();
  };
};

module.exports = {
  authenticateJWT,
  authorizeRoles,
};
