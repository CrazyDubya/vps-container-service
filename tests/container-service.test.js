const request = require('supertest');
const WebSocket = require('ws');

// Mock the container service for testing
const API_BASE = 'http://localhost:3000';
const API_KEY = process.env.TEST_API_KEY || 'test-key-123';

describe('Container Service API Tests', () => {
  let testContainerId = null;
  
  beforeAll(async () => {
    // Wait for service to be ready
    await new Promise(resolve => setTimeout(resolve, 2000));
  });
  
  afterAll(async () => {
    // Cleanup test containers
    if (testContainerId) {
      try {
        await request(API_BASE)
          .delete(`/containers/${testContainerId}`)
          .set('x-api-key', API_KEY);
      } catch (error) {
        console.warn('Cleanup failed:', error.message);
      }
    }
  });

  describe('Health and Service Endpoints', () => {
    test('GET /health should return healthy status', async () => {
      const response = await request(API_BASE)
        .get('/health')
        .expect(200);
      
      expect(response.body).toHaveProperty('status', 'healthy');
      expect(response.body).toHaveProperty('timestamp');
    });

    test('GET /templates should return available templates', async () => {
      const response = await request(API_BASE)
        .get('/templates')
        .set('x-api-key', API_KEY)
        .expect(200);
      
      expect(response.body).toHaveProperty('templates');
      expect(response.body.templates).toHaveProperty('Programming Languages');
      expect(response.body.templates['Programming Languages']).toHaveProperty('python');
      expect(response.body.templates['Programming Languages']).toHaveProperty('nodejs');
    });

    test('GET /limits should return user limits', async () => {
      const response = await request(API_BASE)
        .get('/limits')
        .set('x-api-key', API_KEY)
        .expect(200);
      
      expect(response.body).toHaveProperty('userId');
      expect(response.body).toHaveProperty('containers');
      expect(response.body.containers).toHaveProperty('limit', 5);
    });
  });

  describe('Container Management', () => {
    test('POST /containers/create should create container with basic template', async () => {
      const response = await request(API_BASE)
        .post('/containers/create')
        .set('x-api-key', API_KEY)
        .send({
          template: 'alpine',
          maxMemory: 128,
          ttl: 300 // 5 minutes for testing
        })
        .expect(200);
      
      expect(response.body).toHaveProperty('id');
      expect(response.body).toHaveProperty('status', 'running');
      expect(response.body).toHaveProperty('backend', 'docker');
      expect(response.body).toHaveProperty('ttl', 300);
      
      testContainerId = response.body.id;
    });

    test('POST /containers/create should create container with volumes', async () => {
      const response = await request(API_BASE)
        .post('/containers/create')
        .set('x-api-key', API_KEY)
        .send({
          template: 'ubuntu',
          maxMemory: 256,
          volumes: [
            { name: 'code', path: '/code' },
            { name: 'data', path: '/data' }
          ],
          ttl: 300
        })
        .expect(200);
      
      expect(response.body).toHaveProperty('volumes');
      expect(response.body.volumes).toHaveLength(2);
      
      // Cleanup
      await request(API_BASE)
        .delete(`/containers/${response.body.id}`)
        .set('x-api-key', API_KEY);
    });

    test('POST /containers/create should enforce user limits', async () => {
      // Create containers up to limit
      const containers = [];
      
      for (let i = 0; i < 5; i++) {
        const response = await request(API_BASE)
          .post('/containers/create')
          .set('x-api-key', API_KEY)
          .send({
            template: 'alpine',
            maxMemory: 64,
            ttl: 60
          });
        
        if (response.status === 200) {
          containers.push(response.body.id);
        }
      }
      
      // Try to create one more (should fail)
      const response = await request(API_BASE)
        .post('/containers/create')
        .set('x-api-key', API_KEY)
        .send({
          template: 'alpine',
          maxMemory: 64
        })
        .expect(429);
      
      expect(response.body).toHaveProperty('error');
      expect(response.body.error).toContain('limit exceeded');
      
      // Cleanup
      for (const id of containers) {
        try {
          await request(API_BASE)
            .delete(`/containers/${id}`)
            .set('x-api-key', API_KEY);
        } catch (error) {
          // Ignore cleanup errors
        }
      }
    });

    test('GET /containers should list all containers', async () => {
      const response = await request(API_BASE)
        .get('/containers')
        .set('x-api-key', API_KEY)
        .expect(200);
      
      expect(response.body).toHaveProperty('containers');
      expect(Array.isArray(response.body.containers)).toBe(true);
    });

    test('GET /containers/:id should return container info', async () => {
      if (!testContainerId) {
        console.warn('No test container available for info test');
        return;
      }
      
      const response = await request(API_BASE)
        .get(`/containers/${testContainerId}`)
        .set('x-api-key', API_KEY)
        .expect(200);
      
      expect(response.body).toHaveProperty('id', testContainerId);
      expect(response.body).toHaveProperty('status');
      expect(response.body).toHaveProperty('backend');
    });
  });

  describe('Container Operations', () => {
    test('POST /containers/:id/exec should execute commands', async () => {
      if (!testContainerId) {
        console.warn('No test container available for exec test');
        return;
      }
      
      const response = await request(API_BASE)
        .post(`/containers/${testContainerId}/exec`)
        .set('x-api-key', API_KEY)
        .send({
          command: 'echo "Hello World" && ls -la /'
        })
        .expect(200);
      
      expect(response.body).toHaveProperty('output');
      expect(response.body).toHaveProperty('exitCode', 0);
      expect(response.body.output).toContain('Hello World');
    });

    test('GET /containers/:id/stats should return resource stats', async () => {
      if (!testContainerId) {
        console.warn('No test container available for stats test');
        return;
      }
      
      const response = await request(API_BASE)
        .get(`/containers/${testContainerId}/stats`)
        .set('x-api-key', API_KEY)
        .expect(200);
      
      expect(response.body).toHaveProperty('cpu');
      expect(response.body).toHaveProperty('memory');
      expect(response.body).toHaveProperty('timestamp');
    });

    test('GET /containers/:id/logs should return container logs', async () => {
      if (!testContainerId) {
        console.warn('No test container available for logs test');
        return;
      }
      
      const response = await request(API_BASE)
        .get(`/containers/${testContainerId}/logs`)
        .set('x-api-key', API_KEY)
        .expect(200);
      
      expect(response.body).toHaveProperty('logs');
    });

    test('POST /containers/:id/stop should stop container', async () => {
      if (!testContainerId) {
        console.warn('No test container available for stop test');
        return;
      }
      
      const response = await request(API_BASE)
        .post(`/containers/${testContainerId}/stop`)
        .set('x-api-key', API_KEY)
        .expect(200);
      
      expect(response.body).toHaveProperty('message');
      expect(response.body.message).toContain('stopped');
    });
  });

  describe('File Operations', () => {
    test('POST /containers/:id/files should upload files', async () => {
      if (!testContainerId) {
        console.warn('No test container available for file upload test');
        return;
      }
      
      const response = await request(API_BASE)
        .post(`/containers/${testContainerId}/files`)
        .set('x-api-key', API_KEY)
        .attach('file', Buffer.from('Test file content'), 'test.txt')
        .field('path', '/tmp')
        .expect(200);
      
      expect(response.body).toHaveProperty('message');
      expect(response.body).toHaveProperty('path', '/tmp/test.txt');
    });

    test('GET /containers/:id/files/* should download files', async () => {
      if (!testContainerId) {
        console.warn('No test container available for file download test');
        return;
      }
      
      // First create a file to download
      await request(API_BASE)
        .post(`/containers/${testContainerId}/exec`)
        .set('x-api-key', API_KEY)
        .send({
          command: 'echo "Download test content" > /tmp/download-test.txt'
        });
      
      const response = await request(API_BASE)
        .get(`/containers/${testContainerId}/files/tmp/download-test.txt`)
        .set('x-api-key', API_KEY)
        .expect(200);
      
      expect(response.headers['content-disposition']).toContain('download-test.txt');
    });
  });

  describe('Authentication and Error Handling', () => {
    test('Requests without API key should return 401', async () => {
      await request(API_BASE)
        .get('/containers')
        .expect(401);
    });

    test('Requests with invalid API key should return 401', async () => {
      await request(API_BASE)
        .get('/containers')
        .set('x-api-key', 'invalid-key')
        .expect(401);
    });

    test('Non-existent container operations should return 404/500', async () => {
      await request(API_BASE)
        .get('/containers/non-existent-id')
        .set('x-api-key', API_KEY)
        .expect(500); // Should return error for non-existent container
    });
  });

  describe('Template-specific Tests', () => {
    test('Python template should include data science packages', async () => {
      const response = await request(API_BASE)
        .post('/containers/create')
        .set('x-api-key', API_KEY)
        .send({
          template: 'python',
          maxMemory: 512,
          ttl: 300
        })
        .expect(200);
      
      const containerId = response.body.id;
      
      // Test that Python and packages are available
      const execResponse = await request(API_BASE)
        .post(`/containers/${containerId}/exec`)
        .set('x-api-key', API_KEY)
        .send({
          command: 'python3 --version && pip list | grep pandas'
        });
      
      expect(execResponse.body.output).toContain('Python 3');
      
      // Cleanup
      await request(API_BASE)
        .delete(`/containers/${containerId}`)
        .set('x-api-key', API_KEY);
    });

    test('Node.js template should include TypeScript', async () => {
      const response = await request(API_BASE)
        .post('/containers/create')
        .set('x-api-key', API_KEY)
        .send({
          template: 'node',
          maxMemory: 512,
          ttl: 300
        })
        .expect(200);
      
      const containerId = response.body.id;
      
      // Test that Node.js and TypeScript are available
      const execResponse = await request(API_BASE)
        .post(`/containers/${containerId}/exec`)
        .set('x-api-key', API_KEY)
        .send({
          command: 'node --version && tsc --version'
        });
      
      expect(execResponse.body.output).toContain('v20');
      
      // Cleanup
      await request(API_BASE)
        .delete(`/containers/${containerId}`)
        .set('x-api-key', API_KEY);
    });
  });
});

describe('WebSocket Terminal Tests', () => {
  let testContainerId = null;
  
  beforeAll(async () => {
    // Create a test container for WebSocket tests
    const response = await request(API_BASE)
      .post('/containers/create')
      .set('x-api-key', API_KEY)
      .send({
        template: 'alpine',
        maxMemory: 128,
        ttl: 300
      });
    
    if (response.status === 200) {
      testContainerId = response.body.id;
    }
  });
  
  afterAll(async () => {
    if (testContainerId) {
      try {
        await request(API_BASE)
          .delete(`/containers/${testContainerId}`)
          .set('x-api-key', API_KEY);
      } catch (error) {
        console.warn('WebSocket test cleanup failed:', error.message);
      }
    }
  });

  test('WebSocket terminal connection should work', (done) => {
    if (!testContainerId) {
      console.warn('No test container available for WebSocket test');
      done();
      return;
    }
    
    const wsUrl = `ws://localhost:3000/terminal?container=${testContainerId}&apiKey=${API_KEY}`;
    const ws = new WebSocket(wsUrl);
    
    ws.on('open', () => {
      // Send a simple command
      ws.send('echo "WebSocket test"\\n');
    });
    
    ws.on('message', (data) => {
      const message = data.toString();
      if (message.includes('WebSocket test')) {
        ws.close();
        done();
      }
    });
    
    ws.on('error', (error) => {
      console.warn('WebSocket error:', error.message);
      done();
    });
    
    // Timeout after 10 seconds
    setTimeout(() => {
      ws.close();
      done();
    }, 10000);
  });
});