# API Key Security Implementation

## Overview

API keys are now stored using bcrypt hashing for enhanced security. This prevents API keys from being exposed if the database is compromised.

## Changes Made

### 1. API Key Hashing
- API keys are generated as 32-byte random hex strings
- They are hashed using bcrypt (10 rounds) before storage
- The plaintext API key is only shown once during:
  - User registration
  - API key regeneration

### 2. API Key Authentication
- When authenticating with an API key, the system:
  - Retrieves all active users
  - Compares the provided key against each user's hashed key
  - Returns the matching user if found

### 3. JWT Secret Persistence
- JWT secret is now stored in `.env` file
- Prevents token invalidation on service restart
- Run `node setup-jwt-secret.js` to generate a persistent secret

## Migration

Existing API keys have been migrated to hashed format:
- A backup table `users_backup` was created
- All plaintext API keys were hashed
- To restore: `DROP TABLE users; ALTER TABLE users_backup RENAME TO users;`

## Usage

### Regenerating API Key
```bash
curl -X POST http://localhost:3000/auth/regenerate-api-key \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

This returns the new API key in plaintext - save it immediately as it won't be shown again.

### Using API Keys
```bash
curl http://localhost:3000/containers \
  -H "X-API-Key: YOUR_API_KEY"
```

## Security Notes

1. **API keys are shown only once** - during creation or regeneration
2. **JWT tokens expire** - default is 24 hours
3. **Use HTTPS in production** - to prevent key interception
4. **Store keys securely** - in environment variables or secure key management systems