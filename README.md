# 🐳 CF Container Service

An enterprise-grade cloud development platform providing on-demand containerized environments with advanced features.

## 🎯 Overview

The CF Container Service transforms basic container orchestration into a full-featured cloud development environment with WebSocket terminals, persistent volumes, resource monitoring, and comprehensive lifecycle management.

## ✨ Features

### 🚀 **Core Container Management**
- Create, start, stop, and delete containers via REST API
- Auto-detection between Docker and LXC backends
- Container lifecycle with TTL and automatic cleanup
- User quotas and resource limits (5 containers per user by default)

### 📦 **Enhanced Templates**
- **13 pre-configured environments** across multiple categories:
  - **Base Systems:** Ubuntu 22.04, Alpine Linux
  - **Programming Languages:** Python 3.11, Node.js 20, Go 1.21, Rust 1.75, Java 21
  - **Web Servers:** Nginx, Apache
  - **Databases:** PostgreSQL 15, Redis 7
  - **AI/ML:** PyTorch, TensorFlow
- Language-specific tools and packages pre-installed
- Optimized volume mappings and environment variables

### 💾 **Persistent Storage**
- Volume mounting with host directory mapping
- Default `/workspace` volume for all containers
- Custom volume configuration with automatic cleanup
- File upload/download with 10MB limit

### 🖥️ **Interactive Terminals**
- Real-time WebSocket terminal access
- Full TTY support with proper encoding
- Multiple concurrent terminal sessions
- Clean command execution with exit codes

### 📊 **Resource Monitoring**
- CPU, memory, network, and disk usage stats
- Container performance metrics
- Resource limit enforcement
- Health monitoring endpoints

### 🔐 **Security & Authentication**
- API key authentication for all endpoints
- Per-user container tracking and limits
- Secure file operations with proper cleanup
- CORS support for web applications

## 🚀 Quick Start

### Prerequisites
- Docker installed and running
- Node.js 18+ 
- Linux environment (tested on Ubuntu 22.04)

### Installation

```bash
# Clone the repository
git clone https://github.com/CrazyDubya/vps-container-service.git
cd vps-container-service

# Install dependencies
npm install

# Start the service
npm start
```

The service will start on port 3000 and display the API key for authentication.

### Environment Variables
```bash
API_KEY=your-secret-api-key
PORT=3000
MAX_CONTAINERS_PER_USER=5
DEFAULT_CONTAINER_TTL=3600
CLEANUP_INTERVAL=300000
```

## 📚 API Reference

### Authentication
All API endpoints require the `x-api-key` header:
```bash
curl -H "x-api-key: YOUR_API_KEY" http://localhost:3000/health
```

### Core Endpoints

#### Container Management
```bash
# Create container with template
POST /containers/create
{
  "template": "python",
  "maxMemory": 512,
  "volumes": [{"name": "data", "path": "/data"}],
  "ttl": 3600
}

# List containers
GET /containers

# Get container info
GET /containers/:id

# Stop container
POST /containers/:id/stop

# Delete container
DELETE /containers/:id
```

#### Container Operations
```bash
# Execute command
POST /containers/:id/exec
{"command": "python --version"}

# Get resource stats
GET /containers/:id/stats

# Get logs
GET /containers/:id/logs?lines=100
```

#### File Operations
```bash
# Upload file
POST /containers/:id/files
# (multipart form with file and path fields)

# Download file
GET /containers/:id/files/path/to/file
```

#### System Endpoints
```bash
# Service health
GET /health

# Available templates
GET /templates

# User limits and usage
GET /limits
```

### WebSocket Terminal
```javascript
const ws = new WebSocket('ws://localhost:3000/terminal?container=CONTAINER_ID&apiKey=API_KEY');
ws.on('open', () => ws.send('echo "Hello World"\\n'));
ws.on('message', (data) => console.log(data.toString()));
```

## 🧪 Testing

### Run Tests
```bash
# Full test suite with service management
npm test

# Unit tests only
npm run test:unit

# Watch mode for development
npm run test:watch

# Load testing
node tests/load-test.js --url http://localhost:3000 --key YOUR_API_KEY
```

### Test Coverage
- ✅ All API endpoints
- ✅ WebSocket terminals
- ✅ File operations
- ✅ Authentication & error handling
- ✅ Template functionality
- ✅ Load testing & performance

## 🏗️ Architecture

```
CF Container Service
├── 🌐 REST API (Express.js)
├── 🔌 WebSocket Server (ws)
├── 🐳 Docker Backend (dockerode)
├── 📁 Volume Management
├── 🧪 Test Suite (Jest)
└── 📊 Monitoring & Stats
```

### Key Components
- **container-service.js**: Main API server with all endpoints
- **lib/docker-backend.js**: Docker container operations
- **lib/backend-factory.js**: Backend abstraction layer
- **tests/**: Comprehensive test suite with load testing

## 🔧 Development

### Available Scripts
```bash
npm start      # Start production server
npm run dev    # Development with auto-reload
npm test       # Full test suite
npm run test:unit  # Unit tests only
npm run test:watch # Watch mode
```

### Adding New Templates
Templates are defined in `container-service.js`. Each template includes:
```javascript
'template-name': {
  image: 'docker-image:tag',
  workdir: '/workspace',
  env: ['ENV_VAR=value'],
  init: ['setup command 1', 'setup command 2'],
  volumes: [{name: 'vol1', path: '/path'}],
  ports: {'80/tcp': '8080'}
}
```

## 🚀 Production Deployment

### Systemd Service
```ini
[Unit]
Description=CF Container Service
After=docker.service

[Service]
Type=simple
User=cfworker-admin
WorkingDirectory=/home/cfworker-admin/cf-container-service
ExecStart=/usr/bin/node container-service.js
Restart=always
Environment=NODE_ENV=production
Environment=API_KEY=your-production-key

[Install]
WantedBy=multi-user.target
```

### Security Considerations
- Use strong API keys in production
- Configure firewall rules for port access
- Regular cleanup of expired containers
- Monitor resource usage and set appropriate limits
- Use HTTPS in production with reverse proxy

## 📊 Performance

### Benchmarks
- **Health Check:** ~100 req/s
- **Container Creation:** ~5 containers/s
- **Command Execution:** ~50 req/s
- **File Operations:** 10MB uploads supported

### Resource Requirements
- **Memory:** 512MB minimum, 2GB recommended
- **Storage:** 10GB for volumes and containers
- **CPU:** 2 cores recommended for concurrent operations

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Make changes and add tests
4. Run test suite: `npm test`
5. Commit changes: `git commit -m 'Add amazing feature'`
6. Push to branch: `git push origin feature/amazing-feature`
7. Create Pull Request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🎉 Acknowledgments

- Built with Docker, Node.js, and Express
- Testing with Jest and SuperTest
- WebSocket terminals with ws library
- Inspired by cloud development platforms

---

**🤖 Generated with [Claude Code](https://claude.ai/code)**

**Co-Authored-By: Claude <noreply@anthropic.com>**

For support and questions, please create an issue in the GitHub repository.