#!/usr/bin/env node

const http = require('http');
const { performance } = require('perf_hooks');

class LoadTester {
  constructor(options = {}) {
    this.baseUrl = options.baseUrl || 'http://localhost:3000';
    this.apiKey = options.apiKey || 'test-api-key';
    this.concurrency = options.concurrency || 10;
    this.duration = options.duration || 30000; // 30 seconds
    this.results = {
      totalRequests: 0,
      successfulRequests: 0,
      failedRequests: 0,
      avgResponseTime: 0,
      minResponseTime: Infinity,
      maxResponseTime: 0,
      responseTimes: [],
      errors: []
    };
  }

  async makeRequest(endpoint, method = 'GET', data = null) {
    const start = performance.now();
    
    return new Promise((resolve) => {
      const url = new URL(endpoint, this.baseUrl);
      const options = {
        method,
        headers: {
          'x-api-key': this.apiKey,
          'Content-Type': 'application/json'
        }
      };

      const req = http.request(url, options, (res) => {
        let responseData = '';
        
        res.on('data', (chunk) => {
          responseData += chunk;
        });
        
        res.on('end', () => {
          const end = performance.now();
          const responseTime = end - start;
          
          resolve({
            success: res.statusCode >= 200 && res.statusCode < 300,
            statusCode: res.statusCode,
            responseTime,
            data: responseData
          });
        });
      });

      req.on('error', (error) => {
        const end = performance.now();
        const responseTime = end - start;
        
        resolve({
          success: false,
          error: error.message,
          responseTime
        });
      });

      if (data) {
        req.write(JSON.stringify(data));
      }
      
      req.end();
    });
  }

  async runTest(testName, testFunction, requests = 100) {
    console.log(`\n🧪 Running ${testName}...`);
    
    const promises = [];
    const startTime = performance.now();
    
    for (let i = 0; i < requests; i++) {
      promises.push(testFunction());
      
      // Add small delay to avoid overwhelming the service
      if (i % this.concurrency === 0) {
        await new Promise(resolve => setTimeout(resolve, 10));
      }
    }
    
    const results = await Promise.all(promises);
    const endTime = performance.now();
    const totalTime = endTime - startTime;
    
    // Process results
    const successCount = results.filter(r => r.success).length;
    const failCount = results.length - successCount;
    const responseTimes = results.map(r => r.responseTime);
    const avgResponseTime = responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length;
    
    console.log(`  ✅ Successful: ${successCount}/${requests}`);
    console.log(`  ❌ Failed: ${failCount}/${requests}`);
    console.log(`  ⚡ Avg Response Time: ${avgResponseTime.toFixed(2)}ms`);
    console.log(`  🕒 Total Time: ${totalTime.toFixed(2)}ms`);
    console.log(`  📊 Requests/sec: ${(requests / (totalTime / 1000)).toFixed(2)}`);
    
    return {
      testName,
      requests,
      successful: successCount,
      failed: failCount,
      avgResponseTime,
      totalTime,
      requestsPerSecond: requests / (totalTime / 1000)
    };
  }

  async healthCheckTest() {
    return this.runTest('Health Check Load Test', () => {
      return this.makeRequest('/health');
    }, 50);
  }

  async containerListTest() {
    return this.runTest('Container List Load Test', () => {
      return this.makeRequest('/containers');
    }, 30);
  }

  async templateListTest() {
    return this.runTest('Template List Load Test', () => {
      return this.makeRequest('/templates');
    }, 20);
  }

  async containerCreateTest() {
    return this.runTest('Container Creation Load Test', () => {
      return this.makeRequest('/containers/create', 'POST', {
        template: 'alpine',
        maxMemory: 64,
        ttl: 60 // 1 minute TTL for load test containers
      });
    }, 5); // Limited to avoid resource exhaustion
  }

  async run() {
    console.log('🚀 Starting Load Test Suite');
    console.log('=' .repeat(50));
    console.log(`Target: ${this.baseUrl}`);
    console.log(`Concurrency: ${this.concurrency}`);
    console.log(`Duration: ${this.duration}ms`);
    
    const testResults = [];
    
    try {
      // Test 1: Health Check
      testResults.push(await this.healthCheckTest());
      
      // Test 2: Container List
      testResults.push(await this.containerListTest());
      
      // Test 3: Template List
      testResults.push(await this.templateListTest());
      
      // Test 4: Container Creation (limited)
      testResults.push(await this.containerCreateTest());
      
      // Summary
      console.log('\n📊 Load Test Summary');
      console.log('=' .repeat(50));
      
      testResults.forEach(result => {
        console.log(`${result.testName}:`);
        console.log(`  Success Rate: ${((result.successful / result.requests) * 100).toFixed(1)}%`);
        console.log(`  Avg Response: ${result.avgResponseTime.toFixed(2)}ms`);
        console.log(`  Throughput: ${result.requestsPerSecond.toFixed(2)} req/s`);
        console.log('');
      });
      
      const overallStats = {
        totalRequests: testResults.reduce((sum, r) => sum + r.requests, 0),
        totalSuccessful: testResults.reduce((sum, r) => sum + r.successful, 0),
        avgResponseTime: testResults.reduce((sum, r) => sum + r.avgResponseTime, 0) / testResults.length
      };
      
      console.log('🎯 Overall Performance:');
      console.log(`  Total Requests: ${overallStats.totalRequests}`);
      console.log(`  Success Rate: ${((overallStats.totalSuccessful / overallStats.totalRequests) * 100).toFixed(1)}%`);
      console.log(`  Avg Response Time: ${overallStats.avgResponseTime.toFixed(2)}ms`);
      
      if (overallStats.totalSuccessful / overallStats.totalRequests > 0.95) {
        console.log('✅ Load test PASSED - Service performance is excellent');
        return 0;
      } else {
        console.log('⚠️  Load test WARNING - Service performance needs attention');
        return 1;
      }
      
    } catch (error) {
      console.error('❌ Load test FAILED:', error.message);
      return 2;
    }
  }
}

// CLI interface
if (require.main === module) {
  const args = process.argv.slice(2);
  const options = {};
  
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i].replace('--', '');
    const value = args[i + 1];
    
    switch (key) {
      case 'url':
        options.baseUrl = value;
        break;
      case 'key':
        options.apiKey = value;
        break;
      case 'concurrency':
        options.concurrency = parseInt(value);
        break;
      case 'duration':
        options.duration = parseInt(value);
        break;
    }
  }
  
  const tester = new LoadTester(options);
  tester.run().then(exitCode => {
    process.exit(exitCode);
  }).catch(error => {
    console.error('Fatal error:', error);
    process.exit(3);
  });
}

module.exports = LoadTester;