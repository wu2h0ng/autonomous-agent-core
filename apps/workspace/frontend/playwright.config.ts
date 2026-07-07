import { defineConfig, devices } from '@playwright/test';

const PORT = process.env.PLAYWRIGHT_PORT ?? '3099';
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${PORT}`;

// Match production Docker entrypoint: `output: "standalone"` is incompatible with `next start`.
const standaloneStart = [
  'npm run build',
  'cp -r public .next/standalone/public',
  'mkdir -p .next/standalone/.next',
  'cp -r .next/static .next/standalone/.next/static',
  `PORT=${PORT} HOSTNAME=127.0.0.1 node .next/standalone/server.js`,
].join(' && ');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: standaloneStart,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
