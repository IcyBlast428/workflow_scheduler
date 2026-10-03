import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  workers: 1,
  timeout: 45000,
  use: { baseURL: 'http://127.0.0.1:19008', trace: 'retain-on-failure',
    launchOptions:process.env.WFS_BROWSER_EXECUTABLE ? {executablePath:process.env.WFS_BROWSER_EXECUTABLE} : {} },
  webServer: {
    command: `${process.env.WFS_BROWSER_PYTHON || 'python3'} ../scripts/browser_test_server.py`,
    url: 'http://127.0.0.1:19008/api/user/ready',
    timeout: 30000,
    reuseExistingServer: false,
  },
});
