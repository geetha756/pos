#!/usr/bin/env node

/**
 * Browser Testing Script for Sip & Snack Portal
 * 
 * This script uses Puppeteer to test your Flask application running at http://127.0.0.1:5000
 * 
 * Usage:
 *   1. Make sure your Flask app is running: python app.py
 *   2. Install dependencies: npm install puppeteer
 *   3. Run the test: node browser-test.js
 */

const puppeteer = require('puppeteer');

const BASE_URL = 'http://127.0.0.1:5000';
const TIMEOUT = 30000; // 30 seconds

// Test results
const results = {
  passed: [],
  failed: [],
  warnings: []
};

/**
 * Log test results
 */
function logResult(testName, passed, message = '') {
  const status = passed ? '✅ PASS' : '❌ FAIL';
  console.log(`${status}: ${testName}${message ? ' - ' + message : ''}`);
  
  if (passed) {
    results.passed.push(testName);
  } else {
    results.failed.push({ test: testName, message });
  }
}

/**
 * Wait for page to be ready
 */
async function waitForPageReady(page) {
  try {
    await page.waitForSelector('body', { timeout: 5000 });
  } catch (error) {
    // Ignore timeout errors
  }
}

/**
 * Test 1: Homepage loads successfully
 */
async function testHomepageLoads(page) {
  try {
    console.log('\n📄 Test 1: Homepage loads successfully');
    const response = await page.goto(BASE_URL, { 
      waitUntil: 'networkidle2',
      timeout: TIMEOUT 
    });
    
    if (response && response.status() === 200) {
      logResult('Homepage loads', true, `Status: ${response.status()}`);
      return true;
    } else {
      logResult('Homepage loads', false, `Status: ${response?.status() || 'No response'}`);
      return false;
    }
  } catch (error) {
    logResult('Homepage loads', false, error.message);
    return false;
  }
}

/**
 * Test 2: Check for console errors
 */
async function testConsoleErrors(page) {
  try {
    console.log('\n🔍 Test 2: Check for console errors');
    const errors = [];
    
    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });
    
    await page.goto(BASE_URL, { waitUntil: 'networkidle2', timeout: TIMEOUT });
    await page.waitForTimeout(2000); // Wait for any async errors
    
    if (errors.length === 0) {
      logResult('No console errors', true);
      return true;
    } else {
      logResult('No console errors', false, `${errors.length} error(s) found`);
      errors.forEach(err => console.log(`   - ${err}`));
      results.warnings.push({ test: 'Console errors', errors });
      return false;
    }
  } catch (error) {
    logResult('No console errors', false, error.message);
    return false;
  }
}

/**
 * Test 3: Check page title
 */
async function testPageTitle(page) {
  try {
    console.log('\n📋 Test 3: Check page title');
    await page.goto(BASE_URL, { waitUntil: 'networkidle2', timeout: TIMEOUT });
    const title = await page.title();
    
    if (title && title.trim() !== '') {
      logResult('Page has title', true, `Title: "${title}"`);
      return true;
    } else {
      logResult('Page has title', false, 'Title is empty');
      return false;
    }
  } catch (error) {
    logResult('Page has title', false, error.message);
    return false;
  }
}

/**
 * Test 4: Check for login page elements (if redirected to login)
 */
async function testLoginPage(page) {
  try {
    console.log('\n🔐 Test 4: Check login page elements');
    await page.goto(BASE_URL, { waitUntil: 'networkidle2', timeout: TIMEOUT });
    
    // Wait a bit for redirects
    await page.waitForTimeout(1000);
    
    const currentUrl = page.url();
    const hasLoginButton = await page.$('button[type="submit"], a[href*="auth"], .btn-primary, input[type="submit"]')
      .then(el => el !== null)
      .catch(() => false);
    
    const hasForm = await page.$('form')
      .then(el => el !== null)
      .catch(() => false);
    
    if (currentUrl.includes('/auth') || currentUrl.includes('/login') || hasLoginButton || hasForm) {
      logResult('Login page accessible', true, `URL: ${currentUrl}`);
      return true;
    } else {
      logResult('Login page accessible', false, 'Could not find login elements');
      return false;
    }
  } catch (error) {
    logResult('Login page accessible', false, error.message);
    return false;
  }
}

/**
 * Test 5: Take screenshot
 */
async function testScreenshot(page) {
  try {
    console.log('\n📸 Test 5: Take screenshot');
    await page.goto(BASE_URL, { waitUntil: 'networkidle2', timeout: TIMEOUT });
    await page.waitForTimeout(1000);
    
    const screenshotPath = 'test-screenshot.png';
    await page.screenshot({ 
      path: screenshotPath, 
      fullPage: true 
    });
    
    logResult('Screenshot taken', true, `Saved to: ${screenshotPath}`);
    return true;
  } catch (error) {
    logResult('Screenshot taken', false, error.message);
    return false;
  }
}

/**
 * Test 6: Check network requests
 */
async function testNetworkRequests(page) {
  try {
    console.log('\n🌐 Test 6: Check network requests');
    const requests = [];
    const failedRequests = [];
    
    page.on('request', request => {
      requests.push({
        url: request.url(),
        method: request.method()
      });
    });
    
    page.on('requestfailed', request => {
      failedRequests.push({
        url: request.url(),
        failure: request.failure()?.errorText || 'Unknown'
      });
    });
    
    await page.goto(BASE_URL, { waitUntil: 'networkidle2', timeout: TIMEOUT });
    await page.waitForTimeout(2000);
    
    console.log(`   Total requests: ${requests.length}`);
    
    if (failedRequests.length === 0) {
      logResult('Network requests', true, `${requests.length} requests, all successful`);
      return true;
    } else {
      logResult('Network requests', false, `${failedRequests.length} failed request(s)`);
      failedRequests.forEach(req => {
        console.log(`   - Failed: ${req.url} (${req.failure})`);
      });
      results.warnings.push({ test: 'Network requests', failed: failedRequests });
      return false;
    }
  } catch (error) {
    logResult('Network requests', false, error.message);
    return false;
  }
}

/**
 * Test 7: Check page load performance
 */
async function testPagePerformance(page) {
  try {
    console.log('\n⚡ Test 7: Check page load performance');
    
    const startTime = Date.now();
    await page.goto(BASE_URL, { waitUntil: 'networkidle2', timeout: TIMEOUT });
    const loadTime = Date.now() - startTime;
    
    const metrics = await page.metrics();
    
    if (loadTime < 5000) {
      logResult('Page load performance', true, `Loaded in ${loadTime}ms`);
      console.log(`   Metrics: ${JSON.stringify(metrics, null, 2)}`);
      return true;
    } else {
      logResult('Page load performance', false, `Slow load time: ${loadTime}ms`);
      return false;
    }
  } catch (error) {
    logResult('Page load performance', false, error.message);
    return false;
  }
}

/**
 * Main test runner
 */
async function runTests() {
  console.log('🚀 Starting Browser Tests for Sip & Snack Portal');
  console.log(`📍 Testing URL: ${BASE_URL}\n`);
  
  let browser;
  
  try {
    // Launch browser
    console.log('🌐 Launching browser...');
    browser = await puppeteer.launch({
      headless: true, // Set to false to see the browser
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    const page = await browser.newPage();
    
    // Set viewport
    await page.setViewport({ width: 1280, height: 720 });
    
    // Run all tests
    await testHomepageLoads(page);
    await testConsoleErrors(page);
    await testPageTitle(page);
    await testLoginPage(page);
    await testScreenshot(page);
    await testNetworkRequests(page);
    await testPagePerformance(page);
    
    // Print summary
    console.log('\n' + '='.repeat(50));
    console.log('📊 TEST SUMMARY');
    console.log('='.repeat(50));
    console.log(`✅ Passed: ${results.passed.length}`);
    console.log(`❌ Failed: ${results.failed.length}`);
    console.log(`⚠️  Warnings: ${results.warnings.length}`);
    
    if (results.failed.length > 0) {
      console.log('\n❌ Failed Tests:');
      results.failed.forEach(f => {
        console.log(`   - ${f.test}: ${f.message}`);
      });
    }
    
    if (results.warnings.length > 0) {
      console.log('\n⚠️  Warnings:');
      results.warnings.forEach(w => {
        console.log(`   - ${w.test}`);
      });
    }
    
    const exitCode = results.failed.length > 0 ? 1 : 0;
    console.log(`\n${exitCode === 0 ? '✅ All tests passed!' : '❌ Some tests failed'}`);
    
    process.exit(exitCode);
    
  } catch (error) {
    console.error('\n❌ Fatal error:', error.message);
    console.error(error.stack);
    process.exit(1);
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

// Run tests if this script is executed directly
if (require.main === module) {
  runTests().catch(error => {
    console.error('Unhandled error:', error);
    process.exit(1);
  });
}

module.exports = { runTests };

