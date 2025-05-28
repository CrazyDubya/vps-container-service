#!/usr/bin/env node

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

// Configuration
const SERVICE_PORT = process.env.PORT || 3000;
const API_KEY = process.env.API_KEY || 'test-api-key-for-automated-testing';
const TEST_TIMEOUT = 300000; // 5 minutes

class TestRunner {
  constructor() {
    this.serviceProcess = null;
    this.testResults = {
      passed: 0,
      failed: 0,
      skipped: 0,
      errors: []
    };
  }

  async startService() {
    console.log('🚀 Starting container service for testing...');
    
    // Set test environment
    process.env.API_KEY = API_KEY;
    process.env.TEST_API_KEY = API_KEY;
    process.env.PORT = SERVICE_PORT;
    
    return new Promise((resolve, reject) => {
      this.serviceProcess = spawn('node', ['container-service.js'], {
        stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...process.env, NODE_ENV: 'test' }
      });
      
      let output = '';
      
      this.serviceProcess.stdout.on('data', (data) => {
        output += data.toString();
        if (output.includes('Container service running on port')) {
          console.log(`✅ Service started on port ${SERVICE_PORT}`);
          console.log(`🔑 API Key: ${API_KEY}`);
          resolve();
        }
      });
      
      this.serviceProcess.stderr.on('data', (data) => {
        console.error('Service error:', data.toString());
      });
      
      this.serviceProcess.on('error', (error) => {
        reject(new Error(`Failed to start service: ${error.message}`));
      });
      
      // Timeout after 30 seconds
      setTimeout(() => {
        reject(new Error('Service startup timeout'));
      }, 30000);
    });
  }

  async stopService() {
    if (this.serviceProcess) {
      console.log('🛑 Stopping container service...');
      this.serviceProcess.kill('SIGTERM');
      
      // Wait for graceful shutdown
      await new Promise((resolve) => {
        this.serviceProcess.on('exit', resolve);
        setTimeout(resolve, 5000); // Force after 5 seconds
      });
    }
  }

  async runTests() {
    console.log('🧪 Running comprehensive test suite...');
    
    return new Promise((resolve, reject) => {
      const jestProcess = spawn('npx', ['jest', '--verbose', '--detectOpenHandles'], {
        stdio: 'inherit',
        env: {
          ...process.env,
          TEST_API_KEY: API_KEY,
          API_BASE: `http://localhost:${SERVICE_PORT}`
        }
      });
      
      jestProcess.on('exit', (code) => {
        if (code === 0) {
          console.log('✅ All tests passed!');
          resolve();
        } else {
          console.log(`❌ Tests failed with exit code: ${code}`);
          reject(new Error(`Tests failed with exit code: ${code}`));
        }
      });
      
      jestProcess.on('error', (error) => {
        reject(new Error(`Test execution failed: ${error.message}`));
      });
    });
  }

  async runHealthCheck() {
    console.log('🏥 Running pre-test health check...');
    
    const http = require('http');
    
    return new Promise((resolve, reject) => {
      const req = http.get(`http://localhost:${SERVICE_PORT}/health`, (res) => {
        let data = '';
        
        res.on('data', (chunk) => {
          data += chunk;
        });
        
        res.on('end', () => {
          try {
            const response = JSON.parse(data);
            if (response.status === 'healthy') {
              console.log('✅ Service health check passed');
              resolve();
            } else {
              reject(new Error('Service health check failed'));
            }
          } catch (error) {
            reject(new Error('Invalid health check response'));
          }
        });
      });
      
      req.on('error', (error) => {
        reject(new Error(`Health check failed: ${error.message}`));
      });
      
      req.setTimeout(5000, () => {
        req.destroy();
        reject(new Error('Health check timeout'));
      });
    });
  }

  async generateReport() {
    const report = {
      timestamp: new Date().toISOString(),
      service: {
        port: SERVICE_PORT,
        apiKey: API_KEY.substring(0, 8) + '...',
        version: '1.0.0'
      },
      environment: {
        node: process.version,
        platform: process.platform,
        arch: process.arch
      },
      results: this.testResults
    };
    
    const reportPath = path.join(__dirname, 'test-report.json');
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
    
    console.log(`📊 Test report saved to: ${reportPath}`);
    return report;
  }

  async run() {
    console.log('🎯 Starting Container Service Test Suite');
    console.log('=' .repeat(50));
    
    let exitCode = 0;
    
    try {
      // Start the service
      await this.startService();
      
      // Wait a moment for service to fully initialize
      await new Promise(resolve => setTimeout(resolve, 3000));
      
      // Run health check
      await this.runHealthCheck();
      
      // Run the test suite
      await this.runTests();
      
      console.log('🎉 Test suite completed successfully!');
      
    } catch (error) {
      console.error('❌ Test suite failed:', error.message);
      exitCode = 1;
      
    } finally {
      // Always stop the service
      await this.stopService();
      
      // Generate report
      await this.generateReport();
    }
    
    process.exit(exitCode);
  }
}

// Run if called directly
if (require.main === module) {
  const runner = new TestRunner();
  runner.run().catch((error) => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
}

module.exports = TestRunner;