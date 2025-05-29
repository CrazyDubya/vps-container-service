/**
 * Custom Error Class for Operational Errors.
 * These are errors that are expected and handled, where the message can be sent to the client.
 */
class OperationalError extends Error {
  constructor(message, statusCode) {
    super(message);
    this.statusCode = statusCode;
    this.isOperational = true; // Mark as an operational error
    // Maintains proper stack trace in V8 environments (like Node.js)
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, this.constructor);
    }
    this.name = this.constructor.name; // Ensure error name is correct
  }
}

module.exports = OperationalError;
