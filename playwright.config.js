// @ts-check
const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/e2e',
  testMatch: '*.spec.js',
  globalSetup: require.resolve('./tests/e2e/global-setup.js'),
  fullyParallel: false, // Staff Management tests share seeded DB rows/tabs state - run serially for determinism
  workers: 1,
  retries: 0,
  reporter: [
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['json', { outputFile: 'test-report/results/results.json' }],
    ['list'],
  ],
  use: {
    baseURL: 'http://localhost:5000',
    storageState: './tests/e2e/.auth/admin-state.json',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
