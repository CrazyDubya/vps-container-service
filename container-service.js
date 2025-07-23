// Main entry point for CF Container Service
// This file serves as the unified entry point for the container service

// Load the current version of the service
module.exports = require('./container-service-v2.js');

// If this file is executed directly (not required), start the service
if (require.main === module) {
    // The container-service-v2.js will handle the actual server startup
    require('./container-service-v2.js');
}