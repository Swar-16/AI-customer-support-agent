// apps/web/playwright.config.ts

import process from 'node:process';
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },

  reporter: 'dot',
  outputDir: './test-results',
  preserveOutput: 'never',

  use: {
    baseURL: 'http://localhost:5173',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    command: 'npm run dev -- --host localhost --port 5173',
    url: 'http://localhost:5173',
    reuseExistingServer: false,
    timeout: 30_000,
    env: {
      // Credentials belong to the test runner, not the frontend process.
      E2E_ADMIN_EMAIL: '',
      E2E_ADMIN_PASSWORD: '',
      E2E_CUSTOMER_EMAIL: '',
      E2E_CUSTOMER_PASSWORD: '',
      E2E_LIVE_AI: '',
    },
  },
});
