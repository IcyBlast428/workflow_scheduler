import { defineConfig } from '@playwright/test';
if (process.env.WFS_LIVE_POSTGRES_TEST !== 'true') {
  throw new Error('Explicitly set WFS_LIVE_POSTGRES_TEST=true for local PostgreSQL acceptance');
}
export default defineConfig({
  testDir: './live-tests', workers: 1, timeout: 90000,
  expect: { timeout: 20000 },
  use: { baseURL: 'http://127.0.0.1:18008',
    launchOptions: process.env.WFS_BROWSER_EXECUTABLE ? { executablePath: process.env.WFS_BROWSER_EXECUTABLE } : {} },
});
