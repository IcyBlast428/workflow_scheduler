import { test, expect } from '@playwright/test';

async function login(page, hash) {
  await page.goto('/#' + hash);
  await page.getByLabel('用户名', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}

const box = locator => locator.boundingBox();

test('execution log date filters stay together with equal widths and reachable actions', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page, 'taskLogs');
  const form = page.locator('.filter-grid.logs');
  await expect(form).toBeVisible();
  for (const width of [1440, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    const start = await box(form.locator('#task-log-start'));
    const end = await box(form.locator('#task-log-end'));
    const actions = await box(form.locator('.filter-actions'));
    expect(Math.abs(start.width - end.width)).toBeLessThan(1);
    if (width > 480) {
      expect(Math.abs(start.y - end.y)).toBeLessThan(1);
      expect(end.x).toBeGreaterThanOrEqual(start.x + start.width);
    } else {
      expect(end.y).toBeGreaterThanOrEqual(start.y + start.height);
    }
    expect(actions.y).toBeGreaterThanOrEqual(end.y + end.height);
    for (const bounds of [start, end, actions]) {
      expect(bounds.x).toBeGreaterThanOrEqual(0);
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(form.getByRole('button', { name: '搜索', exact: true })).toBeEnabled();
    await expect(form.getByRole('button', { name: '清空', exact: true })).toBeEnabled();
  }
});

test('platform settings loading feedback stays compact and preserves navigation position', async ({ page }) => {
  await login(page, 'admin?section=audit');
  const panel = page.locator('.admin-panel');
  const loading = panel.locator(':scope > .loading-status');
  const navigation = panel.getByRole('navigation', { name: '平台设置分组' });
  await expect(loading).toHaveAttribute('aria-busy', 'false');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    const head = await box(panel.locator(':scope > .panel-head'));
    const before = await box(navigation);
    expect((await box(loading)).height).toBeLessThanOrEqual(4);
    expect(before.y - head.y - head.height).toBeLessThanOrEqual(4);
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    await page.route('**/api/admin/audit', async route => {
      await gate;
      await route.continue();
    });
    await panel.locator(':scope > .panel-head').getByRole('button', { name: '刷新', exact: true }).click();
    await expect(loading).toHaveAttribute('aria-busy', 'true');
    await expect(loading.getByRole('status')).toHaveText('正在更新维护状态与账户…');
    const during = await box(navigation);
    expect(Math.abs(during.y - before.y)).toBeLessThan(1);
    release();
    await expect(loading).toHaveAttribute('aria-busy', 'false');
    await page.unroute('**/api/admin/audit');
    const after = await box(navigation);
    expect(Math.abs(after.y - before.y)).toBeLessThan(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
