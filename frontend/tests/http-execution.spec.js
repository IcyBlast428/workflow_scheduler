import { test, expect } from '@playwright/test';

// A non-localhost HTTP origin exercises the browser restriction itself.
test.use({
  baseURL: 'http://wfs-http.test:19008',
  launchOptions: {
    ...(process.env.WFS_BROWSER_EXECUTABLE ? { executablePath: process.env.WFS_BROWSER_EXECUTABLE } : {}),
    args: ['--host-resolver-rules=MAP wfs-http.test 127.0.0.1', '--no-proxy-server'],
  },
});

test('manual execution works over ordinary HTTP without randomUUID', async ({ page, context }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#tasks');
  expect(await page.evaluate(() => ({
    secure: isSecureContext,
    uuid: typeof crypto.randomUUID,
    random: typeof crypto.getRandomValues,
  }))).toEqual({ secure: false, uuid: 'undefined', random: 'function' });
  await page.getByLabel('用户名', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.app-shell')).toBeVisible();
  expect((await context.cookies()).some(cookie => cookie.name === 'wfs_browser_acceptance_session' && !cookie.secure)).toBe(true);
  const responsePromise = page.waitForResponse(response => response.url().includes('/api/taskinfo/call_task') && response.request().method() === 'POST');
  const row = page.locator('.task-table tbody tr').filter({ hasText: 'acceptance__slow' });
  await row.getByRole('button', { name: '手动执行', exact: true }).click();
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  expect(response.request().postDataJSON().request_id).toMatch(/^[0-9a-f]{32}$/);
  expect((await response.json()).code).toBe(20000);
  await expect(page.locator('.execution-output')).toContainText('浏览器回归完成', { timeout: 30000 });
  await expect(page.getByLabel('执行摘要')).toContainText('成功');
  expect(errors).toEqual([]);
});
