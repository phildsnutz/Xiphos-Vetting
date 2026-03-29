import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.HELIOS_BASE_URL || 'http://127.0.0.1:8080';

export default defineConfig({
  testDir: './',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 1,
  reporter: [
    ['list'],
    ['html'],
  ],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1600, height: 1200 },
      },
    },
  ],
  webServer: undefined,
  timeout: 30 * 1000,
  expect: {
    timeout: 5000,
  },
  navigationTimeout: 60 * 1000,
});
