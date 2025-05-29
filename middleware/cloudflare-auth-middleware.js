const jwt = require('jsonwebtoken');
const crypto = require('crypto');
const cloudflareAuthService = require('../lib/cloudflare-auth-service');
const userModel = require('../lib/user-model');
const OperationalError = require('../lib/operational-error'); 
const db = require('../lib/database'); // For checking if any user exists for first admin logic

const CLOUDFLARE_TEAM_DOMAIN = process.env.CLOUDFLARE_TEAM_DOMAIN;
const CLOUDFLARE_AUDIENCE_TAG = process.env.CLOUDFLARE_AUDIENCE_TAG;

// Helper to count users - used for first user admin logic
const countUsers = () => {
  return new Promise((resolve, reject) => {
    db.get("SELECT COUNT(*) as count FROM users", (err, row) => {
      if (err) {
        return reject(new Error(`Error counting users: ${err.message}`));
      }
      resolve(row ? row.count : 0);
    });
  });
};


/**
 * Middleware to authenticate a Cloudflare Access JWT.
 * If valid, performs JIT provisioning and attaches user payload to req.user.
 */
const authenticateCloudflareJWT = async (req, res, next) => {
  if (!CLOUDFLARE_TEAM_DOMAIN || !CLOUDFLARE_AUDIENCE_TAG) {
    // Cloudflare Access authentication is not configured, skip this middleware.
    return next();
  }

  const cfAssertionToken = req.headers['cf-access-jwt-assertion'];

  if (!cfAssertionToken) {
    // No Cloudflare token present, skip this middleware (allows fallback to other auth).
    return next();
  }

  try {
    const cfPayload = await cloudflareAuthService.verifyCloudflareJWT(cfAssertionToken);

    if (cfPayload && cfPayload.email) {
      let localUser = await userModel.findUserByUsername(cfPayload.email);

      if (!localUser) {
        // Just-In-Time (JIT) Provisioning
        console.log(`JIT Provisioning: User with email ${cfPayload.email} not found. Creating new user.`);
        // Generate a secure random password for local storage; Cloudflare handles primary auth.
        const randomPassword = crypto.randomBytes(16).toString('hex');
        
        let role = 'user';
        const totalUsers = await countUsers();
        if (totalUsers === 0) {
            role = 'admin'; // First user ever (local or CF) becomes admin
            console.log(`JIT Provisioning: First user (${cfPayload.email}), assigning admin role.`);
        }

        try {
            localUser = await userModel.createUser(cfPayload.email, randomPassword, role);
            console.log(`JIT Provisioning: User ${localUser.username} (ID: ${localUser.id}) created with role '${localUser.role}'.`);
        } catch (creationError) {
            // Handle rare case where user might have been created between findUser and createUser (race condition)
            if (creationError.message.includes('Username already exists')) {
                console.warn(`JIT Provisioning: User ${cfPayload.email} already exists (race condition). Fetching again.`);
                localUser = await userModel.findUserByUsername(cfPayload.email);
                if (!localUser) { // Should not happen if previous error was 'Username already exists'
                     return next(new OperationalError('Failed to provision or find user after race condition.', 500));
                }
            } else {
                return next(new OperationalError(`JIT Provisioning error: ${creationError.message}`, 500));
            }
        }
      }
      
      // Attach user information to the request object
      req.user = {
        userId: localUser.id, // Ensure this matches what local JWT strategy sets (userId vs id)
        username: localUser.username,
        role: localUser.role,
        authMethod: 'cloudflare', // Indicate authentication method
        cloudflareIdentity: cfPayload // Optionally store the full CF payload if needed later
      };
      console.log(`User ${req.user.username} authenticated via Cloudflare Access.`);
      return next();

    } else {
      // Token was present but invalid (or payload didn't contain email)
      // verifyCloudflareJWT logs errors, so we can just proceed to next auth method or let it fail.
      // For stricter control, could return 401 here if CF token is present but invalid.
      console.warn('Cloudflare JWT present but invalid or missing email claim.');
      // To force failure if a CF token is present but invalid:
      // return next(new OperationalError('Invalid Cloudflare Access token.', 401)); 
      return next(); // Allow fallback for now
    }
  } catch (error) {
    // Catch errors from verifyCloudflareJWT or userModel calls
    console.error('Error during Cloudflare JWT authentication or JIT provisioning:', error);
    // Don't send error response directly, let subsequent auth middleware or route decide access.
    // For stricter control, could return 500 here.
    return next(); // Allow fallback for now
  }
};

module.exports = {
  authenticateCloudflareJWT,
};
