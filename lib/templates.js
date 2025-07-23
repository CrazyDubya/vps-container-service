/**
 * Centralized Container Templates
 * 
 * Defines all available container templates with their configurations.
 * Used across multiple backends (LXD, Docker, LXC) and service endpoints.
 */

const templates = {
    // Base Operating Systems
    'ubuntu': {
        name: 'Ubuntu 22.04',
        description: 'Ubuntu 22.04 LTS with development tools',
        category: 'base',
        image: 'ubuntu:22.04',
        init: ['apt-get update', 'apt-get install -y curl wget vim nano htop git build-essential'],
        env: ['DEBIAN_FRONTEND=noninteractive'],
        workdir: '/workspace',
        defaultMemory: 512
    },
    
    'alpine': {
        name: 'Alpine Linux',
        description: 'Lightweight Alpine Linux container',
        category: 'base',
        image: 'alpine:latest',
        init: ['apk update', 'apk add --no-cache curl wget vim nano htop git build-base'],
        workdir: '/workspace',
        defaultMemory: 256
    },

    // Programming Languages
    'python': {
        name: 'Python 3.11',
        description: 'Python 3.11 with data science libraries',
        category: 'language',
        image: 'python:3.11-slim',
        init: [
            'apt-get update && apt-get install -y git curl',
            'pip install --upgrade pip setuptools wheel',
            'pip install requests numpy pandas matplotlib jupyter ipython flask fastapi'
        ],
        env: ['PYTHONUNBUFFERED=1', 'PYTHONPATH=/workspace'],
        workdir: '/workspace',
        volumes: [
            {name: 'pip-cache', path: '/root/.cache/pip'},
            {name: 'notebooks', path: '/workspace/notebooks'}
        ],
        defaultMemory: 1024
    },

    'node': {
        name: 'Node.js 20',
        description: 'Node.js 20 with development tools',
        category: 'language',
        image: 'node:20-slim',
        init: [
            'apt-get update && apt-get install -y git curl python3 make g++',
            'npm install -g typescript ts-node nodemon express-generator yarn pnpm pm2'
        ],
        env: ['NODE_ENV=development'],
        workdir: '/workspace',
        volumes: [
            {name: 'npm-cache', path: '/root/.npm'},
            {name: 'node_modules', path: '/workspace/node_modules'}
        ],
        defaultMemory: 768
    },

    // Alias for node.js
    'nodejs': {
        name: 'Node.js 20',
        description: 'Node.js 20 with development tools',
        category: 'language',
        image: 'node:20-slim',
        init: [
            'apt-get update && apt-get install -y git curl python3 make g++',
            'npm install -g typescript ts-node nodemon express-generator yarn pnpm pm2'
        ],
        env: ['NODE_ENV=development'],
        workdir: '/workspace',
        volumes: [
            {name: 'npm-cache', path: '/root/.npm'},
            {name: 'node_modules', path: '/workspace/node_modules'}
        ],
        defaultMemory: 768
    },

    'go': {
        name: 'Go 1.21',
        description: 'Go 1.21 with development tools',
        category: 'language',
        image: 'golang:1.21-alpine',
        init: [
            'apk add --no-cache git curl make gcc musl-dev',
            'go install github.com/air-verse/air@latest',
            'go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest'
        ],
        env: ['GO111MODULE=on', 'GOPROXY=https://proxy.golang.org', 'GOPATH=/go'],
        workdir: '/go/src/app',
        volumes: [{name: 'go-modules', path: '/go/pkg/mod'}],
        defaultMemory: 512
    },

    'rust': {
        name: 'Rust 1.75',
        description: 'Rust 1.75 with Cargo tools',
        category: 'language',
        image: 'rust:1.75-slim',
        init: [
            'apt-get update && apt-get install -y git curl pkg-config libssl-dev',
            'rustup component add rustfmt clippy',
            'cargo install cargo-watch cargo-edit'
        ],
        env: ['RUST_BACKTRACE=1', 'CARGO_HOME=/workspace/.cargo'],
        workdir: '/workspace',
        volumes: [{name: 'cargo-registry', path: '/usr/local/cargo/registry'}],
        defaultMemory: 1024
    },

    'java': {
        name: 'OpenJDK 21',
        description: 'OpenJDK 21 with Maven and Gradle',
        category: 'language',
        image: 'openjdk:21-slim',
        init: [
            'apt-get update && apt-get install -y curl wget git',
            'apt-get install -y maven gradle'
        ],
        env: ['JAVA_TOOL_OPTIONS=-XX:+UseContainerSupport'],
        workdir: '/workspace',
        volumes: [{name: 'maven-repo', path: '/root/.m2'}],
        defaultMemory: 1024
    },

    // Web Servers
    'nginx': {
        name: 'Nginx',
        description: 'Nginx web server',
        category: 'web',
        image: 'nginx:alpine',
        init: ['apk add --no-cache curl'],
        workdir: '/usr/share/nginx/html',
        ports: {'80/tcp': '8080'},
        volumes: [
            {name: 'html', path: '/usr/share/nginx/html'},
            {name: 'conf', path: '/etc/nginx/conf.d'}
        ],
        defaultMemory: 256
    },

    'apache': {
        name: 'Apache HTTP',
        description: 'Apache HTTP server',
        category: 'web',
        image: 'httpd:2.4-alpine',
        init: ['apk add --no-cache curl'],
        workdir: '/usr/local/apache2/htdocs',
        ports: {'80/tcp': '8080'},
        volumes: [
            {name: 'htdocs', path: '/usr/local/apache2/htdocs'},
            {name: 'conf', path: '/usr/local/apache2/conf'}
        ],
        defaultMemory: 256
    },

    // Databases
    'postgres': {
        name: 'PostgreSQL 15',
        description: 'PostgreSQL 15 database server',
        category: 'database',
        image: 'postgres:15-alpine',
        env: ['POSTGRES_PASSWORD=postgres', 'POSTGRES_DB=myapp'],
        init: ['apk add --no-cache curl'],
        ports: {'5432/tcp': '5432'},
        volumes: [
            {name: 'pgdata', path: '/var/lib/postgresql/data'},
            {name: 'scripts', path: '/workspace/scripts'}
        ],
        defaultMemory: 512
    },

    'redis': {
        name: 'Redis 7',
        description: 'Redis key-value store',
        category: 'database',
        image: 'redis:7-alpine',
        init: ['apk add --no-cache curl'],
        ports: {'6379/tcp': '6379'},
        volumes: [{name: 'redis-data', path: '/data'}],
        defaultMemory: 256
    },

    // AI/ML
    'pytorch': {
        name: 'PyTorch',
        description: 'PyTorch with Jupyter and ML libraries',
        category: 'ml',
        image: 'pytorch/pytorch:latest',
        init: [
            'apt-get update && apt-get install -y git curl',
            'pip install jupyter notebook jupyterlab pandas numpy matplotlib seaborn scikit-learn'
        ],
        env: ['PYTHONUNBUFFERED=1', 'JUPYTER_ENABLE_LAB=yes'],
        workdir: '/workspace',
        ports: {'8888/tcp': '8888'},
        volumes: [
            {name: 'notebooks', path: '/workspace/notebooks'},
            {name: 'data', path: '/workspace/data'},
            {name: 'models', path: '/workspace/models'}
        ],
        defaultMemory: 2048
    },

    'tensorflow': {
        name: 'TensorFlow',
        description: 'TensorFlow with Jupyter',
        category: 'ml',
        image: 'tensorflow/tensorflow:latest-jupyter',
        env: ['PYTHONUNBUFFERED=1', 'TF_CPP_MIN_LOG_LEVEL=2'],
        workdir: '/tf/notebooks',
        ports: {'8888/tcp': '8888'},
        volumes: [
            {name: 'notebooks', path: '/tf/notebooks'},
            {name: 'data', path: '/tf/data'}
        ],
        defaultMemory: 2048
    }
};

/**
 * Get template by name
 */
function getTemplate(name) {
    return templates[name] || null;
}

/**
 * List all templates
 */
function listTemplates() {
    return Object.keys(templates).map(name => ({
        name,
        ...templates[name]
    }));
}

/**
 * List templates by category
 */
function getTemplatesByCategory() {
    const categoryMap = {
        'base': 'Base Systems',
        'language': 'Programming Languages',
        'web': 'Web Servers',
        'database': 'Databases',
        'ai': 'AI/ML'
    };
    
    const categories = {};
    Object.keys(templates).forEach(name => {
        const template = templates[name];
        const internalCategory = template.category || 'other';
        const categoryName = categoryMap[internalCategory] || internalCategory;
        
        if (!categories[categoryName]) {
            categories[categoryName] = {};
        }
        categories[categoryName][name] = {
            name,
            title: template.name,
            description: template.description,
            defaultMemory: template.defaultMemory
        };
    });
    return categories;
}

/**
 * Validate template configuration
 */
function validateTemplate(templateName, config = {}) {
    const template = getTemplate(templateName);
    if (!template) {
        throw new Error(`Unknown template: ${templateName}`);
    }

    // Merge template defaults with provided config
    const mergedConfig = {
        ...config,
        image: config.image || template.image,
        workdir: config.workdir || template.workdir || '/workspace',
        env: [...(template.env || []), ...(config.env || [])],
        volumes: [...(template.volumes || []), ...(config.volumes || [])],
        ports: {...(template.ports || {}), ...(config.ports || {})},
        init: template.init || [],
        maxMemory: config.maxMemory || template.defaultMemory || 512
    };

    return mergedConfig;
}

module.exports = {
    templates,
    getTemplate,
    listTemplates,
    getTemplatesByCategory,
    validateTemplate
};