# cf-container-service

## 1. Project Overview

`cf-container-service` is a lightweight, API-driven service designed for programmatic management of both Docker application containers and LXC system containers. It aims to provide a simple, direct, and secure interface for container lifecycle operations, suitable for automation scripts, integration into larger platforms, or scenarios where a full-fledged container orchestration platform is overly complex or resource-intensive. The service supports multiple authentication methods, including local user management with JWT and integration with Cloudflare Access.

## 2. Features

### Core Container Management
*   **Dual Backend Support:** Manage both Docker and LXC containers through a unified API.
*   **Lifecycle Operations:**
    *   Create, start, stop, and remove containers.
    *   List running and all containers.
    *   Execute commands within containers.
    *   Get detailed information and statistics for containers.
*   **Interactive Terminal:** Provides WebSocket-based interactive terminal access to containers.
*   **File I/O:** Upload files to and download files from containers.

### Local User Management
*   **User Registration:** `/auth/register` endpoint for new user creation.
    *   The first user registered automatically becomes an 'admin'.
    *   Subsequent users default to the 'user' role.
*   **JWT-Based Login:** `/auth/login` endpoint provides a JSON Web Token (JWT) upon successful authentication.
*   **Role-Based Access Control (RBAC):**
    *   **Admin Role:** Full access to manage all containers and users (user management endpoints to be added).
    *   **User Role:** Can only manage containers they own.
*   **Container Ownership:** Containers are associated with the user ID of their creator. Users can only perform operations on containers they own, while admins have unrestricted access.

### Cloudflare Access JWT Integration
*   **Zero Trust Authentication:** Optionally integrate with Cloudflare Access for user authentication.
*   **JWT Verification:** Verifies JWTs passed in the `CF-Access-Jwt-Assertion` header against your Cloudflare Team Domain's public keys.
*   **Just-In-Time (JIT) Provisioning:** If a user authenticates successfully via Cloudflare Access but does not have an account in the local database, an account is automatically created for them using their email from the Cloudflare JWT as their username.
    *   The first user provisioned via Cloudflare Access (if no other users exist in the database) becomes an 'admin'. Subsequent JIT users are assigned the 'user' role.

### Crypto-Mining Prevention (Designed Feature)
*This feature's full implementation was planned but partially hindered by tool limitations during development. The configuration and basic checks are designed as follows:*
*   **Suspicious Environment Variable Detection:** During container creation, environment variables are checked against a configurable list of regex patterns commonly associated with crypto-mining (e.g., wallet addresses, pool URLs).
    *   An option (`CRYPTO_REJECT_ON_SUSPICIOUS_ENV`) determines whether to reject container creation or just log a warning if a suspicious pattern is matched.
*   **Suspicious Process Scanning:** A designed API endpoint (`/containers/:id/actions/scan-processes`) would allow scanning running processes within a container against a configurable list of suspicious process names.

## 3. Deployment (`deploy.sh`)

The `deploy.sh` script automates the setup of `cf-container-service` on supported Linux systems (primarily Debian/Ubuntu, with some manual steps for RHEL-based systems).

**Instructions:**

1.  Ensure you have `git` installed.
2.  Clone the repository (if you haven't already):
    ```bash
    git clone <repository_url>
    cd cf-container-service
    ```
3.  Make the script executable:
    ```bash
    chmod +x deploy.sh
    ```
4.  Run the script with `sudo` or as a user with `sudo` privileges:
    ```bash
    sudo ./deploy.sh
    ```
    *(Note: While the script uses `sudo` for package installations and service management, `npm install --production` and some `pm2` commands are run as the current user where appropriate.)*

**Key Prompts During Script Execution:**

The script will guide you through the installation and configuration process, prompting for:
*   **API Key:** For direct service access (e.g., WebSocket terminal authentication). You can auto-generate or provide one.
*   **JWT Secret:** A secret key for signing local user JWTs. You can auto-generate or provide one (min 32 characters).
*   **Service Port:** The port on which the service will listen (default: `8082`).
*   **Cloudflare Access Integration (Optional):**
    *   `CLOUDFLARE_TEAM_DOMAIN`: Your Cloudflare team domain (e.g., `your-team.cloudflareaccess.com`).
    *   `CLOUDFLARE_AUDIENCE_TAG`: The Application Audience (AUD) tag for this application from your Cloudflare Access policy.
*   **Crypto-Mining Prevention Settings (For Designed Features):**
    *   `CRYPTO_SUSPICIOUS_ENV_PATTERNS`: Comma-separated list of regex patterns to detect suspicious environment variables.
    *   `CRYPTO_REJECT_ON_SUSPICIOUS_ENV`: `true` or `false` to reject container creation if a suspicious ENV pattern is matched.
    *   `CRYPTO_SUSPICIOUS_PROCESS_NAMES`: Comma-separated list of process names considered suspicious.

## 4. Configuration (`.env` file variables)

The `deploy.sh` script will help create a `.env` file in the project root. Key variables include:

*   `PORT`: The port on which the service will run. Default: `8082`.
*   `API_KEY`: A static API key. Currently, its primary use is for authenticating WebSocket terminal connections. It can also be considered a master key for direct service access if other authentication methods are bypassed or not applicable.
*   `JWT_SECRET`: A long, random, and secret string used to sign and verify local user JWTs. Critical for the security of local user authentication.
*   `CLOUDFLARE_TEAM_DOMAIN`: (Optional) Your Cloudflare team domain (e.g., `your-team.cloudflareaccess.com`). Required for Cloudflare Access JWT integration.
*   `CLOUDFLARE_AUDIENCE_TAG`: (Optional) The Application Audience (AUD) tag from your Cloudflare Access policy. Required for Cloudflare Access JWT integration.
*   `TOKEN_EXPIRES_IN`: (Optional) Defines the expiration time for local JWTs. Defaults to `24h` if not set. Example: `1h`, `7d`.
*   `CRYPTO_SUSPICIOUS_ENV_PATTERNS`: (Designed Feature) Comma-separated list of regex patterns for detecting suspicious environment variables during container creation.
    *   Example: `"WALLET_ADDRESS=.*,POOL_URL=.*,STRATUM_URL=.*,XMRIG_.*"`
*   `CRYPTO_REJECT_ON_SUSPICIOUS_ENV`: (Designed Feature) Boolean (`true` or `false`). If `true`, container creation will be rejected if any environment variable matches a pattern in `CRYPTO_SUSPICIOUS_ENV_PATTERNS`. Defaults to `false`.
*   `CRYPTO_SUSPICIOUS_PROCESS_NAMES`: (Designed Feature) Comma-separated list of process names considered suspicious for the process scan endpoint.
    *   Example: `"xmrig,nbminer,t-rex,stratum,minerd"`

*(Designed feature settings for CPU threshold-based detection like `CRYPTO_CPU_THRESHOLD_PERCENT`, `CRYPTO_CPU_DURATION_SECONDS`, `CRYPTO_ACTION_ON_HIGH_CPU` were conceptualized but not implemented in the script or application due to tool limitations in prior development stages.)*

## 5. API Endpoints (Summary)

### Authentication (`/auth`)
*   `POST /register`: Register a new local user. The first user becomes an admin.
*   `POST /login`: Log in a local user and receive a JWT.

### Container Management (`/containers`)
*All routes under `/containers` require JWT authentication (either local or Cloudflare Access).*
*   `POST /create`: Create a new container. (Protected by JWT, ownership assigned to user).
*   `GET /`: List containers. (Admins see all; users see only their own).
*   `GET /:id`: Get information about a specific container. (Ownership/admin access enforced).
*   `POST /:id/exec`: Execute a command in a container. (Ownership/admin access enforced).
*   `POST /:id/stop`: Stop a container. (Ownership/admin access enforced).
*   `DELETE /:id`: Remove a container. (Ownership/admin access enforced).
*   `GET /:id/logs`: Get container logs. (Ownership/admin access enforced).
*   `POST /:id/files`: Upload a file to a container. (Ownership/admin access enforced).
*   `GET /:id/files/*`: Download a file from a container. (Ownership/admin access enforced).
*   `GET /:id/stats`: Get container statistics. (Ownership/admin access enforced).
*   `POST /:id/actions/scan-processes`: (Designed Feature) Scan processes in a container for suspicious names. (Ownership/admin access enforced).

### WebSocket Terminal (`/terminal`)
*   Connect via WebSocket to `ws://<host>:<port>/terminal?container=<containerId>&apiKey=<API_KEY>[&backendType=<docker|lxc>]`.
*   Authentication: Uses the static `API_KEY` passed as a query parameter.
*   `backendType` is optional; if omitted, the service will attempt to auto-detect the backend for the given `containerId`.

## 6. Security Considerations

*   **Secret Management:**
    *   `API_KEY`: Keep this key secure. It provides direct access, especially to WebSockets.
    *   `JWT_SECRET`: This is critical for the security of local user accounts. It should be a long, random, and unique string. Do NOT commit it to your repository if you set it manually.
*   **HTTPS:** For production deployments, always run this service behind a reverse proxy that provides HTTPS/TLS encryption (e.g., Nginx, Caddy, or a load balancer). Do not expose the Node.js service directly to the internet over HTTP.
*   **Cloudflare Access:** If using Cloudflare Access integration:
    *   Ensure your Cloudflare Access policies are correctly configured to protect the service origin.
    *   The `CLOUDFLARE_TEAM_DOMAIN` and `CLOUDFLARE_AUDIENCE_TAG` must match your Cloudflare setup exactly.
*   **Database Security:** The SQLite database file (`cf_service.db`) contains user credentials (hashed passwords). Ensure appropriate file permissions are set to protect this file from unauthorized access.
*   **Input Validation:** The service implements input validation, but continuous review and hardening are recommended.
*   **Principle of Least Privilege:** Ensure the user running the `cf-container-service` has only the necessary permissions to interact with Docker and LXC, but no more.
*   **Host Security:** The security of the containers managed by this service heavily depends on the security of the host system. Keep the host updated and secured.

## 7. Development

### Prerequisites
*   Node.js (v18.x or later recommended)
*   npm
*   Docker Engine (for Docker backend)
*   LXC (for LXC backend)

### Local Setup
1.  Clone the repository:
    ```bash
    git clone <repository_url>
    cd cf-container-service
    ```
2.  Install all dependencies (including devDependencies):
    ```bash
    npm install
    ```
3.  Create a `.env` file in the project root. You can copy `.env.example` (if one exists) or create it manually.
    *   Minimal required variables for local development:
        ```env
        API_KEY=your_strong_api_key_here
        JWT_SECRET=your_very_strong_jwt_secret_here_at_least_32_chars
        PORT=8082
        # Add other variables as needed (e.g., for Cloudflare, Crypto prevention)
        ```
4.  Initialize the database (if not done automatically on first run by `lib/database.js`):
    *   The `lib/database.js` module is designed to auto-initialize the DB when the app starts.
5.  Run the service in development mode (e.g., using `nodemon` if configured, or directly):
    ```bash
    npm run dev 
    ```
    or
    ```bash
    node container-service.js
    ```
    The service will typically be available at `http://localhost:8082` (or your configured port).The README.md content has been generated.
