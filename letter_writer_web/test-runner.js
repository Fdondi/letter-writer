#!/usr/bin/env node

/**
 * Test runner script for the Letter Writer Web application
 * 
 * This script provides different test execution modes:
 * - Run all tests
 * - Run tests in watch mode
 * - Run tests with coverage
 * - Run specific test files
 * 
 * Usage:
 *   node test-runner.js [--watch] [--coverage] [--file=<filename>]
 */

import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const args = process.argv.slice(2);
const isWatch = args.includes('--watch');
const isCoverage = args.includes('--coverage');
const fileArg = args.find(arg => arg.startsWith('--file='));
const specificFile = fileArg ? fileArg.split('=')[1] : null;

// Build Jest command
const jestArgs = [];

if (isWatch) {
  jestArgs.push('--watch');
}

if (isCoverage) {
  jestArgs.push('--coverage', '--coverageDirectory=coverage');
}

if (specificFile) {
  jestArgs.push(specificFile);
}

// Add verbose output for better test results
jestArgs.push('--verbose');

// Run Jest
console.log('🧪 Running Letter Writer Web Tests...');
console.log(`Command: npx jest ${jestArgs.join(' ')}`);
console.log('');

const testProcess = spawn('npx', ['jest', ...jestArgs], {
  stdio: 'inherit',
  cwd: __dirname
});

testProcess.on('close', (code) => {
  if (code === 0) {
    console.log('\\n✅ All tests passed!');
    
    if (isCoverage) {
      console.log('📊 Coverage report generated in ./coverage directory');
      console.log('Open ./coverage/lcov-report/index.html to view detailed coverage');
    }
  } else {
    console.log(`\\n❌ Tests failed with exit code ${code}`);
    process.exit(code);
  }
});

testProcess.on('error', (error) => {
  console.error('❌ Failed to start test process:', error);
  process.exit(1);
});

