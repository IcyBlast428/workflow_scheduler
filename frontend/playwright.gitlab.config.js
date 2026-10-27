import base from './playwright.config.js';
import { defineConfig } from '@playwright/test';
export default defineConfig({
  ...base,
  testMatch: ['gitlab-updates.spec.js', 'gitlab-tasks.spec.js'],
  testIgnore: [],
  webServer: { ...base.webServer, env: { ...process.env, WFS_BROWSER_GITLAB_FIXTURE: '1' }, timeout: 45000 },
});
