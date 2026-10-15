import { test, expect } from '@playwright/test';

async function login(page, hash = 'dashboard') {
  await page.goto('/#' + hash);
  await page.getByLabel('用户名', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}

test('readiness failures remain visible even when API requests succeed', async ({ page }) => {
  await page.clock.install();
  await page.route('**/api/user/ready', route => route.fulfill({ status: 503, json: {
    code: 20000, data: { ready: false, components: {
      api: { status: 'ready', message: '接口正常' },
      database: { status: 'unavailable', message: '数据库不可用或迁移未完成' },
      scheduler: { status: 'ready', message: '调度器正常' },
    } },
  } }));
  await page.goto('/');
  await expect(page.getByText('接口已连接，服务尚未就绪', { exact: true })).toBeVisible();
  await page.getByLabel('用户名', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  const status = page.getByRole('status', { name: '服务状态' });
  await expect(status).toContainText('数据库异常');
  await expect(status.locator('[data-status="unavailable"]')).toHaveCount(1);
  await page.unroute('**/api/user/ready');
  await page.clock.fastForward(31000);
  await expect(status).toContainText('数据库正常');
});

test('desktop text navigation can collapse and restores its saved choice', async ({ page }) => {
  await login(page);
  await expect(page.locator('.app-shell')).toHaveClass(/nav-expanded/);
  await page.getByRole('button', { name: '收起导航', exact: true }).click();
  await expect(page.locator('.app-shell')).not.toHaveClass(/nav-expanded/);
  await page.reload();
  await expect(page.locator('.app-shell')).toBeVisible();
  await expect(page.locator('.app-shell')).not.toHaveClass(/nav-expanded/);
  await page.getByRole('button', { name: '展开导航', exact: true }).click();
  await expect(page.locator('.app-shell')).toHaveClass(/nav-expanded/);
});

test('mobile matrix starts in two dimensions and filters expand on demand', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, 'matrix');
  await expect(page.locator('.heatmap-panel')).toBeVisible();
  await expect(page.getByLabel('分类', { exact: true })).not.toBeVisible();
  await page.getByRole('button', { name: '筛选', exact: true }).click();
  await expect(page.getByLabel('矩阵视图')).toHaveValue('2d');
  await page.getByLabel('矩阵视图').selectOption('3d');
  await expect(page.locator('.matrix-surface')).toBeVisible();
  await page.reload();
  await expect(page.locator('.matrix-surface')).toBeVisible();
  await page.getByRole('button', { name: '筛选', exact: true }).click();
  await expect(page.getByLabel('矩阵视图')).toHaveValue('3d');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('extracted and lazy pages remain navigable without script errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page);
  for (const [name, selector] of [
    ['任务列表', '.task-table'], ['执行记录', '.log-shortcuts'],
    ['平台事件', '#system-log-id'], ['任务发布', '.package-panel'],
    ['账户与审计', '.admin-panel'], ['执行矩阵', '.matrix-summary'],
    ['总览', '.cpu-panel'],
  ]) {
    await page.getByRole('button', { name, exact: true }).click();
    await expect(page.locator(selector)).toBeVisible();
  }
  expect(errors).toEqual([]);
});
