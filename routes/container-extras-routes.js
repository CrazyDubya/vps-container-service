const express = require('express');
const BackendFactory = require('../lib/backend-factory');
const OperationalError = require('../lib/operational-error');
const { authenticateJWT } = require('../middleware/auth-middleware');
const { authorizeContainerAccess } = require('../middleware/container-auth-middleware');

const router = express.Router({ mergeParams: true }); // Ensure containerId is available from parent router

// Load crypto process names from environment or use defaults
const CRYPTO_SUSPICIOUS_PROCESS_NAMES_RAW = process.env.CRYPTO_SUSPICIOUS_PROCESS_NAMES || "xmrig,nbminer,t-rex,stratum,minerd,cpuminer,ccminer,ethminer,claymore";
const CRYPTO_SUSPICIOUS_PROCESS_NAMES = CRYPTO_SUSPICIOUS_PROCESS_NAMES_RAW.split(',').map(p => p.trim().toLowerCase()).filter(p => p.length > 0);

/**
 * @swagger
 * /containers/{id}/scan-processes:
 *   post:
 *     summary: Scan running processes in a container for suspicious names
 *     tags: [Containers]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: string
 *         description: The ID of the container
 *     responses:
 *       200:
 *         description: Scan result
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 suspiciousProcessesFound:
 *                   type: boolean
 *                 matches:
 *                   type: array
 *                   items:
 *                     type: string
 *                 count:
 *                   type: integer
 *       400:
 *         description: Invalid input or container not found
 *       401:
 *         description: Unauthorized (JWT missing or invalid)
 *       403:
 *         description: Forbidden (user does not own container or is not admin)
 *       500:
 *         description: Server error or error executing command in container
 */
router.post('/scan-processes', authenticateJWT, authorizeContainerAccess, async (req, res, next) => {
  const containerId = req.params.id;
  const { backendType } = req.query; // Optional: allow specifying backend if known

  if (CRYPTO_SUSPICIOUS_PROCESS_NAMES.length === 0) {
    return res.json({
      suspiciousProcessesFound: false,
      matches: [],
      count: 0,
      message: "No suspicious process names configured for scanning."
    });
  }

  try {
    let backend;
    if (backendType) {
      backend = BackendFactory.create(backendType);
    } else {
      // Auto-detect backend
      try {
        backend = BackendFactory.create('docker');
        await backend.getInfo(containerId); // Check if it's a Docker container
      } catch (dockerError) {
        try {
          backend = BackendFactory.create('lxc');
          await backend.getInfo(containerId); // Check if it's an LXC container
        } catch (lxcError) {
          return next(new OperationalError(`Container ${containerId} not found in any backend or backend detection failed.`, 404));
        }
      }
    }
    
    // Command to list processes. 'ps auxww' is common.
    // For Docker, 'ps aux' within the container. For LXC, 'lxc-attach -- ps aux'.
    // The backend.exec() method should handle the specifics of how to run 'ps auxww'.
    const command = "ps auxww"; 
    const execResult = await backend.exec(containerId, command);

    if (execResult.exitCode !== 0) {
      console.error(`Error executing "ps" in container ${containerId}. Exit code: ${execResult.exitCode}, Error: ${execResult.error || execResult.output}`);
      return next(new OperationalError(`Failed to list processes in container. Exit code: ${execResult.exitCode}. Error: ${execResult.error || execResult.output}`, 500));
    }

    const output = execResult.output;
    const lines = output.split('\n');
    const suspiciousMatches = [];

    lines.forEach(line => {
      const lowerLine = line.toLowerCase();
      for (const suspiciousName of CRYPTO_SUSPICIOUS_PROCESS_NAMES) {
        if (lowerLine.includes(suspiciousName)) {
          suspiciousMatches.push(line.trim());
          break; // Found a match for this line, no need to check other suspicious names
        }
      }
    });

    res.json({
      suspiciousProcessesFound: suspiciousMatches.length > 0,
      matches: suspiciousMatches,
      count: suspiciousMatches.length
    });

  } catch (error) {
    // Handle errors from backend.getInfo or backend.exec if they throw directly
    if (error instanceof OperationalError) return next(error);
    console.error(`Error during process scan for container ${containerId}:`, error);
    return next(new OperationalError('An unexpected error occurred while scanning processes.', 500));
  }
});

module.exports = router;
