const BackendFactory = require('../lib/backend-factory');
const OperationalError = require('../lib/operational-error');

/**
 * Fetches container information and returns its owner's user ID.
 * Tries Docker first, then LXC.
 * @param {string} containerId - The ID of the container.
 * @returns {Promise<string|null>} The cf-userId label/metadata or null if not found/not set.
 * @throws {Error} If container is not found in any backend or other backend error occurs.
 */
async function getContainerOwnerId(containerId) {
  let backend;
  let info;

  // Try Docker
  try {
    backend = BackendFactory.create('docker');
    info = await backend.getInfo(containerId);
    if (info && info.labels && info.labels['cf-userId']) {
      return info.labels['cf-userId'];
    }
    // If found by Docker but no cf-userId label, it's unowned or an issue
    if (info) return null; 
  } catch (dockerError) {
    // If Docker errors with "not found" or similar, try LXC. Otherwise, rethrow.
    // A more specific error check might be needed here based on dockerode's error types.
    // For now, we assume any error means "try next backend or it's a real problem".
    if (!(dockerError.statusCode === 404 || (dockerError.json && dockerError.json.message && dockerError.json.message.toLowerCase().includes('no such container')))) {
        // If it's not a "not found" error, perhaps it's a Docker daemon issue.
        // For simplicity now, we'll still proceed to try LXC, but in a real scenario,
        // we might want to handle this differently.
        console.warn(`Docker backend error (will try LXC): ${dockerError.message}`);
    }
  }

  // Try LXC if not found or no userId in Docker
  try {
    backend = BackendFactory.create('lxc');
    info = await backend.getInfo(containerId); // getInfo in LXC was updated to call getMetadata
    if (info && info.labels && info.labels['cf-userId']) {
      return info.labels['cf-userId'];
    }
    // If found by LXC but no cf-userId, it's unowned or an issue
    if (info) return null;
  } catch (lxcError) {
    if (!(lxcError.message && lxcError.message.toLowerCase().includes('failed to get lxc container info'))) {
        // If it's not a "not found" error from our LXC backend's getInfo.
         console.warn(`LXC backend error: ${lxcError.message}`);
    }
  }
  
  // If we reach here, container was not found in any backend that we could get info from,
  // or it was found but had no owner ID. The getInfo methods should throw if not found.
  // If info was fetched but no userId, that's handled by returning null above.
  // This throw indicates the container itself was not locatable by getInfo.
  throw new OperationalError(`Container ${containerId} not found.`, 404);
}

/**
 * Middleware to authorize container access based on user role and ownership.
 * - Admins can access any container.
 * - Users can only access containers they own (matching cf-userId).
 */
const authorizeContainerAccess = async (req, res, next) => {
  const containerId = req.params.id; // Assuming container ID is in req.params.id

  if (!req.user || !req.user.userId) {
    // Should be caught by authenticateJWT first
    return next(new OperationalError('User authentication details are missing.', 401));
  }

  if (req.user.role === 'admin') {
    return next(); // Admins have full access
  }

  try {
    const ownerId = await getContainerOwnerId(containerId);

    if (ownerId === null) {
        // Container exists but has no owner information or is otherwise restricted
        console.warn(`Container ${containerId} has no owner information or access is restricted.`);
        return next(new OperationalError(`You do not have permission to access container ${containerId}. (No owner info)`, 403));
    }
    
    // User's ID from JWT payload (integer) vs Owner ID from label/metadata (string)
    if (String(req.user.userId) === ownerId) {
      return next(); // User owns the container
    } else {
      console.warn(`User ${req.user.userId} attempt to access unowned container ${containerId} (owned by ${ownerId}).`);
      return next(new OperationalError(`You do not have permission to access container ${containerId}.`, 403));
    }
  } catch (error) {
    // Handle errors from getContainerOwnerId, like 404 if container not found
    if (error instanceof OperationalError) {
      return next(error);
    }
    // For unexpected errors
    console.error(`Error during container access authorization for ${containerId}:`, error);
    return next(new OperationalError('An error occurred while authorizing container access.', 500));
  }
};

module.exports = { authorizeContainerAccess, getContainerOwnerId }; // Export helper for WebSocket if needed later
