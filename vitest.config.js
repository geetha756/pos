const { defineConfig } = require('vitest/config');

module.exports = defineConfig({
  test: {
    environment: 'node', // the harness builds its own jsdom window per-module; no global jsdom env needed
    include: ['tests/unit/**/*.test.js'],
  },
});
