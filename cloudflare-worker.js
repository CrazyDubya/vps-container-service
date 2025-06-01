/**
 * Cloudflare Worker for VPS Container Service
 * Serves the GUI and proxies API calls to the backend server
 */

// Your server configuration (will be overridden by environment variables)
const DEFAULT_BACKEND_SERVER = 'http://containers.conflost.com:3000'; // Use HTTP until proper SSL cert
const DEFAULT_BACKEND_SERVER_HTTPS = 'https://containers.conflost.com:3443';

// HTML content - we'll embed the GUI directly
const HTML_CONTENT = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Container Service - Cloud Development Platform</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1, h2 {
            margin: 0 0 20px 0;
            color: #333;
        }
        .form-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: 500;
        }
        input, select {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }
        button {
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.3s;
            position: relative;
        }
        button:hover {
            background: #0056b3;
        }
        button:disabled {
            background: #6c757d;
            cursor: not-allowed;
            opacity: 0.65;
        }
        .error {
            color: #dc3545;
            margin-top: 10px;
            padding: 10px;
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            border-radius: 4px;
        }
        .success {
            color: #155724;
            margin-top: 10px;
            padding: 10px;
            background: #d4edda;
            border: 1px solid #c3e6cb;
            border-radius: 4px;
        }
        .warning {
            color: #856404;
            margin-top: 10px;
            padding: 10px;
            background: #fff3cd;
            border: 1px solid #ffeeba;
            border-radius: 4px;
        }
        .info-box {
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 15px;
            margin-top: 20px;
        }
        .code {
            font-family: monospace;
            background: #f1f3f4;
            padding: 2px 6px;
            border-radius: 3px;
        }
        .hidden {
            display: none;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        th, td {
            text-align: left;
            padding: 12px;
            border-bottom: 1px solid #ddd;
        }
        th {
            background: #f8f9fa;
            font-weight: 600;
        }
        .tab-nav {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 2px solid #dee2e6;
        }
        .tab {
            padding: 10px 20px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: all 0.3s;
        }
        .tab.active {
            border-bottom-color: #007bff;
            color: #007bff;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,.3);
            border-radius: 50%;
            border-top-color: #fff;
            animation: spin 1s ease-in-out infinite;
            margin-left: 10px;
            vertical-align: middle;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .progress-bar {
            width: 100%;
            height: 20px;
            background: #e9ecef;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }
        .progress-fill {
            height: 100%;
            background: #007bff;
            width: 0%;
            transition: width 0.3s;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 12px;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .status-running {
            background: #d4edda;
            color: #155724;
        }
        .status-stopped {
            background: #f8d7da;
            color: #721c24;
        }
        .status-creating {
            background: #cce5ff;
            color: #004085;
        }
        .container-card {
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
            background: #fff;
            transition: all 0.3s;
        }
        .container-card:hover {
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .stat-card {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #007bff;
        }
        .stat-label {
            color: #6c757d;
            font-size: 0.9em;
        }
        .cf-powered {
            position: fixed;
            bottom: 10px;
            right: 10px;
            background: #f38020;
            color: white;
            padding: 5px 10px;
            border-radius: 4px;
            font-size: 12px;
            opacity: 0.8;
        }
    </style>
</head>
<body>
    <h1>🐳 Container Service - Cloud Development Platform</h1>
    <div class="cf-powered">⚡ Powered by Cloudflare Workers</div>
    
    <div class="container" id="authSection">
        <div class="tab-nav">
            <div class="tab active" onclick="switchTab('login')">Login</div>
            <div class="tab" onclick="switchTab('register')">Register</div>
        </div>
        
        <div id="loginTab" class="tab-content active">
            <h2>Login</h2>
            <form id="loginForm">
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" id="loginUsername" required>
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" id="loginPassword" required>
                </div>
                <button type="submit">Login</button>
                <div id="loginMessage"></div>
            </form>
        </div>
        
        <div id="registerTab" class="tab-content">
            <h2>Register New User</h2>
            <form id="registerForm">
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" id="registerUsername" required minlength="3">
                </div>
                <div class="form-group">
                    <label>Email</label>
                    <input type="email" id="registerEmail" required>
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" id="registerPassword" required minlength="8">
                </div>
                <button type="submit">Register</button>
                <div id="registerMessage"></div>
            </form>
        </div>
    </div>
    
    <div class="container hidden" id="dashboardSection">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
            <h2>Welcome, <span id="username"></span>! <span class="status-badge" id="roleLabel" style="margin-left: 10px;">user</span></h2>
            <button onclick="logout()">Logout</button>
        </div>
        
        <div id="alerts"></div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value" id="activeContainers">0</div>
                <div class="stat-label">Active Containers</div>
            </div>
            <div class="stat-card">
                <div class="stat-value"><span id="containersUsed">0</span>/<span id="containerLimit">5</span></div>
                <div class="stat-label">Container Quota</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="cpuUsage">0%</div>
                <div class="stat-label">Total CPU Usage</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="memoryUsage">0 MB</div>
                <div class="stat-label">Total Memory</div>
            </div>
        </div>
        
        <div class="info-box">
            <h3>Your API Key</h3>
            <div style="display: flex; gap: 10px; align-items: center;">
                <p class="code" id="apiKey" style="flex: 1; margin: 0;">Loading...</p>
                <button onclick="copyApiKey()">Copy</button>
                <button onclick="regenerateApiKey()">Regenerate</button>
            </div>
        </div>
        
        <div class="info-box">
            <h3>🐳 Container Management</h3>
            <div style="margin-bottom: 20px; display: flex; gap: 10px; align-items: center;">
                <button onclick="loadContainers()" id="refreshBtn">
                    <span id="refreshIcon">🔄</span> Refresh Containers
                </button>
                <button onclick="showCreateContainer()" id="createBtn">➕ Create New Container</button>
                <span id="autoRefreshStatus" style="margin-left: auto; color: #6c757d; font-size: 0.9em;">
                    Auto-refresh: <span id="refreshCountdown">30</span>s
                </span>
            </div>
            
            <div id="createContainerForm" class="hidden" style="margin-bottom: 20px; padding: 20px; background: #f0f8ff; border: 2px solid #007bff; border-radius: 8px;">
                <h4>🚀 Create New Container</h4>
                <div id="creationProgress" class="hidden">
                    <div class="progress-bar">
                        <div class="progress-fill" id="progressFill">0%</div>
                    </div>
                    <p id="creationStatus" style="text-align: center; margin-top: 10px;">Initializing...</p>
                </div>
                
                <div id="creationForm">
                    <div class="form-group">
                        <label>Template</label>
                        <select id="containerTemplate" onchange="updateTemplateInfo()">
                            <option value="ubuntu">Ubuntu 22.04 - Base Linux system</option>
                            <option value="python">Python 3.11 - With pip, numpy, pandas</option>
                            <option value="node">Node.js 20 - With npm, yarn, pnpm</option>
                            <option value="go">Go 1.21 - Development environment</option>
                            <option value="rust">Rust 1.75 - With cargo</option>
                            <option value="java">Java 21 - With Maven, Gradle</option>
                            <option value="nginx">Nginx - Web server</option>
                            <option value="postgres">PostgreSQL 15 - Database</option>
                            <option value="redis">Redis 7 - Cache server</option>
                        </select>
                        <small id="templateInfo" style="display: block; margin-top: 5px; color: #6c757d;">
                            Base Ubuntu system with common tools pre-installed
                        </small>
                    </div>
                    <div class="form-group">
                        <label>Memory Limit (MB)</label>
                        <input type="number" id="containerMemory" value="512" min="128" max="2048">
                        <small style="display: block; margin-top: 5px; color: #6c757d;">
                            Recommended: 512MB for most applications
                        </small>
                    </div>
                    <div class="form-group">
                        <label>Lifetime</label>
                        <select id="containerTTL" onchange="updateTTLDisplay()">
                            <option value="3600">1 Hour</option>
                            <option value="7200">2 Hours</option>
                            <option value="14400">4 Hours</option>
                            <option value="28800">8 Hours</option>
                            <option value="86400">24 Hours</option>
                        </select>
                        <small id="ttlInfo" style="display: block; margin-top: 5px; color: #6c757d;">
                            Container will auto-delete after 1 hour
                        </small>
                    </div>
                    <div style="display: flex; gap: 10px;">
                        <button onclick="createContainer()" id="createSubmitBtn">🚀 Create Container</button>
                        <button onclick="hideCreateContainer()" style="background: #6c757d;">Cancel</button>
                    </div>
                </div>
                <div id="createMessage" style="margin-top: 15px;"></div>
            </div>
            
            <div id="containersListArea">
                <div id="containersMessage" style="text-align: center; padding: 20px; color: #6c757d;">
                    <p style="font-size: 1.2em;">Loading containers...</p>
                </div>
                <div id="containersList"></div>
            </div>
        </div>
        
        <div class="info-box">
            <h3>Example API Calls</h3>
            <pre class="code">
# Using API Key
curl -H "x-api-key: YOUR_API_KEY" http://31-97-128-225.nip.io:3000/containers

# Create a Python container
curl -X POST -H "x-api-key: YOUR_API_KEY" \\
     -H "Content-Type: application/json" \\
     -d '{"template": "python"}' \\
     http://31-97-128-225.nip.io:3000/containers/create
            </pre>
        </div>
        
        <div id="adminSection" class="hidden">
            <h3>Admin Panel</h3>
            <button onclick="loadUsers()">Load Users</button>
            <table id="usersTable" class="hidden">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Username</th>
                        <th>Email</th>
                        <th>Role</th>
                        <th>Containers</th>
                        <th>Active</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="usersTableBody"></tbody>
            </table>
        </div>
    </div>

    <script>
        // Use worker proxy for API calls (avoids mixed content issues)
        const API_URL = '';
        
        let authToken = localStorage.getItem('authToken');
        let currentUser = null;

        // Check if already logged in
        if (authToken) {
            loadProfile();
        }

        function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            
            if (tab === 'login') {
                document.querySelector('.tab:first-child').classList.add('active');
                document.getElementById('loginTab').classList.add('active');
            } else {
                document.querySelector('.tab:last-child').classList.add('active');
                document.getElementById('registerTab').classList.add('active');
            }
        }

        // Login form
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('loginUsername').value;
            const password = document.getElementById('loginPassword').value;
            
            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password})
                });
                
                const data = await response.json();
                if (response.ok) {
                    authToken = data.token;
                    localStorage.setItem('authToken', authToken);
                    currentUser = data.user;
                    showDashboard();
                    document.getElementById('loginMessage').innerHTML = '<p class="success">Login successful!</p>';
                } else {
                    document.getElementById('loginMessage').innerHTML = \`<p class="error">\${data.error}</p>\`;
                }
            } catch (error) {
                document.getElementById('loginMessage').innerHTML = '<p class="error">Network error</p>';
            }
        });

        // Register form
        document.getElementById('registerForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('registerUsername').value;
            const email = document.getElementById('registerEmail').value;
            const password = document.getElementById('registerPassword').value;
            
            try {
                const response = await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, email, password})
                });
                
                const data = await response.json();
                if (response.ok) {
                    authToken = data.token;
                    localStorage.setItem('authToken', authToken);
                    currentUser = data.user;
                    showDashboard();
                    document.getElementById('registerMessage').innerHTML = '<p class="success">Registration successful!</p>';
                } else {
                    document.getElementById('registerMessage').innerHTML = \`<p class="error">\${data.error}</p>\`;
                }
            } catch (error) {
                document.getElementById('registerMessage').innerHTML = '<p class="error">Network error</p>';
            }
        });

        async function loadProfile() {
            try {
                const response = await fetch('/api/auth/profile', {
                    headers: {'Authorization': \`Bearer \${authToken}\`}
                });
                
                if (response.ok) {
                    const data = await response.json();
                    currentUser = data;
                    showDashboard();
                } else {
                    localStorage.removeItem('authToken');
                    authToken = null;
                }
            } catch (error) {
                console.error('Failed to load profile');
            }
        }

        function showDashboard() {
            document.getElementById('authSection').classList.add('hidden');
            document.getElementById('dashboardSection').classList.remove('hidden');
            
            document.getElementById('username').textContent = currentUser.username;
            document.getElementById('apiKey').textContent = currentUser.apiKey;
            document.getElementById('containersUsed').textContent = currentUser.containersUsed || 0;
            document.getElementById('containerLimit').textContent = currentUser.containerLimit || 5;
            
            const roleLabel = document.getElementById('roleLabel');
            roleLabel.textContent = currentUser.role;
            roleLabel.className = \`status-badge \${currentUser.role === 'admin' ? 'status-running' : 'status-stopped'}\`;
            
            if (currentUser.role === 'admin') {
                document.getElementById('adminSection').classList.remove('hidden');
            }
            
            // Auto-load containers and start refresh timer
            loadContainers();
            startAutoRefresh();
        }

        function logout() {
            localStorage.removeItem('authToken');
            authToken = null;
            currentUser = null;
            document.getElementById('authSection').classList.remove('hidden');
            document.getElementById('dashboardSection').classList.add('hidden');
        }

        async function regenerateApiKey() {
            try {
                const response = await fetch('/api/auth/regenerate-api-key', {
                    method: 'POST',
                    headers: {'Authorization': \`Bearer \${authToken}\`}
                });
                
                if (response.ok) {
                    const data = await response.json();
                    document.getElementById('apiKey').textContent = data.apiKey;
                    showAlert('API key regenerated successfully!', 'success');
                }
            } catch (error) {
                showAlert('Failed to regenerate API key', 'error');
            }
        }

        // Auto refresh functionality
        let refreshInterval;
        let refreshCountdown = 30;
        
        function startAutoRefresh() {
            if (refreshInterval) clearInterval(refreshInterval);
            refreshCountdown = 30;
            
            refreshInterval = setInterval(() => {
                refreshCountdown--;
                document.getElementById('refreshCountdown').textContent = refreshCountdown;
                
                if (refreshCountdown <= 0) {
                    loadContainers();
                    refreshCountdown = 30;
                }
            }, 1000);
        }
        
        // Container Management Functions
        function showCreateContainer() {
            document.getElementById('createContainerForm').classList.remove('hidden');
            document.getElementById('creationProgress').classList.add('hidden');
            document.getElementById('creationForm').classList.remove('hidden');
            document.getElementById('createMessage').innerHTML = '';
        }

        function hideCreateContainer() {
            document.getElementById('createContainerForm').classList.add('hidden');
            document.getElementById('createMessage').innerHTML = '';
            resetCreationForm();
        }
        
        function resetCreationForm() {
            document.getElementById('creationProgress').classList.add('hidden');
            document.getElementById('creationForm').classList.remove('hidden');
            document.getElementById('createSubmitBtn').disabled = false;
            document.getElementById('createSubmitBtn').innerHTML = '🚀 Create Container';
            const progressFill = document.getElementById('progressFill');
            progressFill.style.width = '0%';
            progressFill.style.background = '#007bff';
            progressFill.textContent = '0%';
            document.getElementById('creationStatus').textContent = 'Initializing...';
        }
        
        function updateTemplateInfo() {
            const template = document.getElementById('containerTemplate').value;
            const info = document.getElementById('templateInfo');
            
            const descriptions = {
                'ubuntu': 'Base Ubuntu system with common tools pre-installed',
                'python': 'Python 3.11 with pip, numpy, pandas, matplotlib, jupyter',
                'node': 'Node.js 20 with npm, yarn, pnpm, nodemon, pm2',
                'go': 'Go 1.21 development environment with git, make, gcc',
                'rust': 'Rust 1.75 with cargo and build essentials',
                'java': 'Java 21 with Maven and Gradle build tools',
                'nginx': 'Nginx web server with Alpine Linux',
                'postgres': 'PostgreSQL 15 database server',
                'redis': 'Redis 7 in-memory data store'
            };
            
            info.textContent = descriptions[template] || 'Custom container configuration';
        }
        
        function updateTTLDisplay() {
            const ttl = parseInt(document.getElementById('containerTTL').value);
            const info = document.getElementById('ttlInfo');
            const hours = Math.floor(ttl / 3600);
            
            if (hours === 1) {
                info.textContent = 'Container will auto-delete after 1 hour';
            } else {
                info.textContent = \`Container will auto-delete after \${hours} hours\`;
            }
        }
        
        function copyApiKey() {
            const apiKey = document.getElementById('apiKey').textContent;
            navigator.clipboard.writeText(apiKey).then(() => {
                showAlert('API key copied to clipboard!', 'success');
            }).catch(() => {
                showAlert('Failed to copy API key', 'error');
            });
        }
        
        function showAlert(message, type = 'info') {
            const alerts = document.getElementById('alerts');
            const alertDiv = document.createElement('div');
            alertDiv.className = type;
            alertDiv.innerHTML = \`
                <strong>\${type === 'error' ? '❌' : type === 'success' ? '✅' : 'ℹ️'}</strong> \${message}
                <button onclick="this.parentElement.remove()" style="float: right; background: none; border: none; font-size: 18px; cursor: pointer;">&times;</button>
            \`;
            alerts.appendChild(alertDiv);
            
            // Auto-remove after 5 seconds
            setTimeout(() => {
                if (alertDiv.parentElement) {
                    alertDiv.remove();
                }
            }, 5000);
        }

        async function createContainer() {
            const submitBtn = document.getElementById('createSubmitBtn');
            const progressDiv = document.getElementById('creationProgress');
            const formDiv = document.getElementById('creationForm');
            const progressFill = document.getElementById('progressFill');
            const statusText = document.getElementById('creationStatus');
            
            try {
                // Start creation process
                submitBtn.disabled = true;
                submitBtn.innerHTML = '🚀 Creating... <span class="spinner"></span>';
                showAlert('Starting container creation...', 'info');
                
                // Show progress bar
                progressDiv.classList.remove('hidden');
                formDiv.classList.add('hidden');
                
                // Animate progress
                let progress = 0;
                const progressInterval = setInterval(() => {
                    progress += Math.random() * 15;
                    if (progress > 85) progress = 85; // Don't complete until we get response
                    progressFill.style.width = \`\${progress}%\`;
                    progressFill.textContent = \`\${Math.round(progress)}%\`;
                }, 200);
                
                // Update status messages
                const statusMessages = [
                    'Initializing container...',
                    'Downloading container image...',
                    'Configuring resources...',
                    'Setting up environment...',
                    'Starting container services...'
                ];
                
                let messageIndex = 0;
                const statusInterval = setInterval(() => {
                    if (messageIndex < statusMessages.length) {
                        statusText.textContent = statusMessages[messageIndex];
                        messageIndex++;
                    }
                }, 1000);
                
                const template = document.getElementById('containerTemplate').value;
                const memory = parseInt(document.getElementById('containerMemory').value);
                const ttl = parseInt(document.getElementById('containerTTL').value);
                
                const response = await fetch('/api/containers/create', {
                    method: 'POST',
                    headers: {
                        'Authorization': \`Bearer \${authToken}\`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        template: template,
                        maxMemory: memory,
                        ttl: ttl
                    })
                });
                
                // Clear intervals
                clearInterval(progressInterval);
                clearInterval(statusInterval);
                
                const data = await response.json();
                if (response.ok) {
                    // Container creation started - now poll for status
                    const containerId = data.id;
                    progressFill.style.width = '40%';
                    progressFill.textContent = '40%';
                    statusText.textContent = 'Container creation initiated...';
                    
                    showAlert(\`⏳ Creating container "\${data.name}"...\`, 'info');
                    
                    // Start polling for status
                    const statusCheckInterval = setInterval(async () => {
                        try {
                            const statusResponse = await fetch(\`\${API_URL}/containers/\${containerId}/status\`, {
                                headers: {'Authorization': \`Bearer \${authToken}\`}
                            });
                            
                            if (statusResponse.ok) {
                                const status = await statusResponse.json();
                                
                                if (status.progress) {
                                    progressFill.style.width = \`\${status.progress}%\`;
                                    progressFill.textContent = \`\${status.progress}%\`;
                                }
                                
                                if (status.message) {
                                    statusText.textContent = status.message;
                                }
                                
                                if (status.status === 'ready') {
                                    clearInterval(statusCheckInterval);
                                    progressFill.style.width = '100%';
                                    progressFill.textContent = '100%';
                                    statusText.textContent = 'Container created successfully!';
                                    
                                    showAlert(\`✅ Container "\${data.name}" is ready!\`, 'success');
                                    
                                    setTimeout(() => {
                                        hideCreateContainer();
                                        loadContainers();
                                        loadProfile();
                                        refreshCountdown = 30;
                                        document.getElementById('refreshCountdown').textContent = refreshCountdown;
                                    }, 2000);
                                } else if (status.status === 'failed') {
                                    clearInterval(statusCheckInterval);
                                    progressFill.style.width = '100%';
                                    progressFill.style.background = '#dc3545';
                                    progressFill.textContent = 'Failed';
                                    statusText.textContent = status.error || 'Container creation failed';
                                    
                                    showAlert(\`❌ Failed to create container: \${status.error}\`, 'error');
                                    
                                    setTimeout(() => {
                                        resetCreationForm();
                                    }, 3000);
                                }
                            }
                        } catch (error) {
                            console.error('Status check error:', error);
                        }
                    }, 1000); // Poll every second
                    
                } else {
                    // Show error state
                    progressFill.style.width = '100%';
                    progressFill.style.background = '#dc3545';
                    progressFill.textContent = 'Failed';
                    statusText.textContent = \`Error: \${data.error}\`;
                    
                    showAlert(\`❌ Failed to create container: \${data.error}\`, 'error');
                    
                    // Reset form after delay
                    setTimeout(() => {
                        resetCreationForm();
                    }, 3000);
                }
            } catch (error) {
                // Clear intervals on error
                clearInterval(progressInterval);
                clearInterval(statusInterval);
                
                progressFill.style.width = '100%';
                progressFill.style.background = '#dc3545';
                progressFill.textContent = 'Error';
                statusText.textContent = 'Network error occurred';
                
                showAlert('❌ Network error - please check your connection', 'error');
                
                setTimeout(() => {
                    resetCreationForm();
                }, 3000);
            }
        }

        async function loadContainers() {
            const refreshBtn = document.getElementById('refreshBtn');
            const refreshIcon = document.getElementById('refreshIcon');
            
            try {
                // Show loading state
                refreshBtn.disabled = true;
                refreshIcon.style.animation = 'spin 1s linear infinite';
                
                const response = await fetch('/api/containers', {
                    headers: {'Authorization': \`Bearer \${authToken}\`}
                });
                
                if (response.ok) {
                    const data = await response.json();
                    displayContainers(data.containers || []);
                    
                    // Update overall stats if available
                    if (data.stats) {
                        document.getElementById('cpuUsage').textContent = data.stats.totalCpu || '0%';
                        document.getElementById('memoryUsage').textContent = data.stats.totalMemory || '0 MB';
                    }
                } else {
                    document.getElementById('containersMessage').innerHTML = \`
                        <div style="text-align: center; padding: 20px; color: #dc3545;">
                            <p style="margin: 0;">⚠️ Failed to load containers</p>
                            <button onclick="loadContainers()" style="margin-top: 10px;">🔄 Try Again</button>
                        </div>
                    \`;
                }
            } catch (error) {
                document.getElementById('containersMessage').innerHTML = \`
                    <div style="text-align: center; padding: 20px; color: #dc3545;">
                        <p style="margin: 0;">🌐 Network error loading containers</p>
                        <button onclick="loadContainers()" style="margin-top: 10px;">🔄 Retry</button>
                    </div>
                \`;
            } finally {
                // Reset loading state
                refreshBtn.disabled = false;
                refreshIcon.style.animation = '';
            }
        }

        function displayContainers(containers) {
            const listArea = document.getElementById('containersList');
            const message = document.getElementById('containersMessage');
            
            // Update stats
            document.getElementById('activeContainers').textContent = containers.filter(c => c.status === 'running').length;
            
            if (containers.length === 0) {
                listArea.innerHTML = '';
                message.innerHTML = \`
                    <div style="text-align: center; padding: 40px; background: #f8f9fa; border-radius: 8px; border: 2px dashed #dee2e6;">
                        <h3 style="color: #6c757d; margin: 0 0 10px 0;">🐳 No containers yet</h3>
                        <p style="color: #6c757d; margin: 0;">Create your first container using the button above!</p>
                    </div>
                \`;
                return;
            }
            
            message.innerHTML = '';
            listArea.innerHTML = containers.map(container => {
                const statusClass = container.status === 'running' ? 'status-running' : 
                                  container.status === 'stopped' ? 'status-stopped' : 'status-creating';
                const timeAgo = getTimeAgo(new Date(container.created));
                
                return \`
                    <div class="container-card">
                        <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 15px;">
                            <div>
                                <h4 style="margin: 0 0 5px 0; color: #333;">
                                    \${container.name || 'Unnamed Container'}
                                    <span class="status-badge \${statusClass}" style="margin-left: 10px;">\${container.status}</span>
                                </h4>
                                <p style="margin: 0; color: #6c757d; font-size: 0.9em;">
                                    <strong>Image:</strong> \${container.image || container.template || 'Unknown'} • 
                                    <strong>Created:</strong> \${timeAgo}
                                </p>
                                <p style="margin: 5px 0 0 0; color: #6c757d; font-size: 0.8em; font-family: monospace;">
                                    ID: \${container.id ? container.id.substring(0, 12) + '...' : 'Unknown'}
                                </p>
                            </div>
                            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                                \${container.status === 'running' ? 
                                    \`<button onclick="openTerminal('\${container.id}')" style="background: #28a745; font-size: 12px; padding: 6px 12px;">🖥️ Terminal</button>\` : 
                                    '<button disabled style="font-size: 12px; padding: 6px 12px;">🖥️ Terminal</button>'
                                }
                                <button onclick="stopContainer('\${container.id}')" 
                                        \${container.status !== 'running' ? 'disabled' : ''} 
                                        style="background: #ffc107; color: #212529; font-size: 12px; padding: 6px 12px;">⏹️ Stop</button>
                                <button onclick="deleteContainer('\${container.id}')" 
                                        style="background: #dc3545; font-size: 12px; padding: 6px 12px;">🗑️ Delete</button>
                            </div>
                        </div>
                    </div>
                \`;
            }).join('');
        }
        
        function getTimeAgo(date) {
            const now = new Date();
            const diffMs = now - date;
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMins / 60);
            const diffDays = Math.floor(diffHours / 24);
            
            if (diffMins < 1) return 'Just now';
            if (diffMins < 60) return \`\${diffMins}m ago\`;
            if (diffHours < 24) return \`\${diffHours}h ago\`;
            if (diffDays < 7) return \`\${diffDays}d ago\`;
            return date.toLocaleDateString();
        }

        async function stopContainer(containerId) {
            if (!confirm('Are you sure you want to stop this container?')) return;
            
            try {
                const response = await fetch(\`\${API_URL}/containers/\${containerId}/stop\`, {
                    method: 'POST',
                    headers: {'Authorization': \`Bearer \${authToken}\`}
                });
                
                if (response.ok) {
                    loadContainers();
                    showAlert('Container stopped successfully', 'success');
                } else {
                    showAlert('Failed to stop container', 'error');
                }
            } catch (error) {
                showAlert('Network error', 'error');
            }
        }

        async function deleteContainer(containerId) {
            if (!confirm('Are you sure you want to delete this container? This action cannot be undone.')) return;
            
            try {
                const response = await fetch(\`\${API_URL}/containers/\${containerId}\`, {
                    method: 'DELETE',
                    headers: {'Authorization': \`Bearer \${authToken}\`}
                });
                
                if (response.ok) {
                    loadContainers();
                    loadProfile(); // Refresh usage stats
                    showAlert('Container deleted successfully', 'success');
                } else {
                    showAlert('Failed to delete container', 'error');
                }
            } catch (error) {
                showAlert('Network error', 'error');
            }
        }

        function openTerminal(containerId) {
            // For now, show instructions - could be enhanced with a web terminal
            const wsUrl = window.location.origin.replace('http', 'ws') + '/api/terminal?container=' + containerId + '&token=' + authToken;
            
            const instructions = \`To connect to this container's terminal, use:

WebSocket URL: \${wsUrl}

Or use the API to execute commands:
curl -X POST "\${window.location.origin}/api/containers/\${containerId}/exec" \\\\
  -H "Authorization: Bearer \${authToken}" \\\\
  -H "Content-Type: application/json" \\\\
  -d '{"command": "ls -la"}'\`;
            
            alert(instructions);
        }

        async function loadUsers() {
            try {
                const response = await fetch('/api/auth/users', {
                    headers: {'Authorization': \`Bearer \${authToken}\`}
                });
                
                if (response.ok) {
                    const data = await response.json();
                    displayUsers(data.users);
                } else {
                    showAlert('Failed to load users', 'error');
                }
            } catch (error) {
                showAlert('Network error', 'error');
            }
        }

        function displayUsers(users) {
            const table = document.getElementById('usersTable');
            const tbody = document.getElementById('usersTableBody');
            
            tbody.innerHTML = users.map(user => \`
                <tr>
                    <td>\${user.id}</td>
                    <td>\${user.username}</td>
                    <td>\${user.email}</td>
                    <td>\${user.role}</td>
                    <td>\${user.containers_used}/\${user.container_limit}</td>
                    <td>\${user.is_active ? 'Yes' : 'No'}</td>
                    <td>
                        <button onclick="toggleUserStatus(\${user.id}, \${!user.is_active})">
                            \${user.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                    </td>
                </tr>
            \`).join('');
            
            table.classList.remove('hidden');
        }

        async function toggleUserStatus(userId, activate) {
            try {
                const response = await fetch(\`\${API_URL}/auth/users/\${userId}\`, {
                    method: 'PATCH',
                    headers: {
                        'Authorization': \`Bearer \${authToken}\`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({isActive: activate})
                });
                
                if (response.ok) {
                    loadUsers();
                    showAlert('User updated successfully', 'success');
                }
            } catch (error) {
                showAlert('Failed to update user', 'error');
            }
        }
    </script>
</body>
</html>`;

// Main worker handler
export default {
  async fetch(request, env, ctx) {
    // Use environment variables if available, otherwise use defaults
    const BACKEND_SERVER = env.BACKEND_SERVER || DEFAULT_BACKEND_SERVER;
    const BACKEND_SERVER_HTTPS = env.BACKEND_SERVER_HTTPS || DEFAULT_BACKEND_SERVER_HTTPS;
    
    const url = new URL(request.url);
    
    // Serve the GUI for the root path
    if (url.pathname === '/' || url.pathname === '/index.html') {
      return new Response(HTML_CONTENT, {
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'public, max-age=300', // 5 minutes cache
        },
      });
    }
    
    // Proxy API requests to backend
    if (url.pathname.startsWith('/api/')) {
      return await proxyToBackend(request, url, BACKEND_SERVER);
    }
    
    // WebSocket upgrade for terminals
    if (url.pathname === '/api/terminal') {
      return await proxyWebSocket(request, url, BACKEND_SERVER);
    }
    
    // 404 for other paths
    return new Response('Not Found', { status: 404 });
  },
};

// Proxy API requests to backend server
async function proxyToBackend(request, url, backendServer) {
  // Remove /api prefix for backend
  const backendPath = url.pathname.replace('/api', '');
  const backendUrl = `${backendServer}${backendPath}${url.search}`;
  
  // Forward the request to backend
  const modifiedRequest = new Request(backendUrl, {
    method: request.method,
    headers: request.headers,
    body: request.body,
    // Note: Cloudflare Workers don't allow disabling certificate validation
    // The backend needs a valid SSL certificate
  });
  
  try {
    const response = await fetch(modifiedRequest);
    
    // Add CORS headers
    const modifiedResponse = new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: {
        ...Object.fromEntries(response.headers),
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, x-api-key',
      },
    });
    
    return modifiedResponse;
  } catch (error) {
    return new Response(JSON.stringify({
      error: 'Backend server unavailable',
      details: error.message
    }), {
      status: 503,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
      },
    });
  }
}

// Proxy WebSocket connections
async function proxyWebSocket(request, url, backendServer) {
  const backendUrl = `${backendServer.replace('http:', 'ws:').replace('https:', 'wss:')}/terminal${url.search}`;
  
  // For now, return instructions since WebSocket proxying in Workers requires more setup
  return new Response(JSON.stringify({
    message: 'WebSocket terminal access',
    websocketUrl: backendUrl,
    instructions: 'Use a WebSocket client to connect to the backend directly'
  }), {
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
    },
  });
}