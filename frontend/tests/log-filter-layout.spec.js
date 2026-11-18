import { test, expect } from '@playwright/test';

async function login(page, hash) {
  await page.goto('/#' + hash);
  await page.getByLabel('用户名', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}

const box = locator => locator.boundingBox();

test('execution log columns remember desktop and phone choices', async ({ page }) => {
  const record = {
    id: 'acceptance__slow',
    logid: 'fixture-log',
    name: '执行记录示例',
    group_name: '验收组',
    folder_name: 'slow',
    state: '成功',
    times: '1',
    starttime: '2026-11-18 07:28:58.462213',
    datetime: '2026-11-18 07:28:59.769494',
  };
  await page.route('**/api/taskinfo/taskLogs*', route => route.fulfill({
    json: { code: 20000, data: { data: [record], total: 1 } },
  }));
  await page.route('**/api/taskinfo/taskLogDetail*', route => route.fulfill({
    json: { code: 20000, data: '执行详情验收' },
  }));
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page, 'taskLogs');

  const workspace = page.locator('.execution-records-pane');
  const desktop = workspace.locator('.log-table-desktop');
  const picker = workspace.locator('.column-picker');
  const trigger = picker.getByText('显示列', { exact: true });
  const options = picker.getByRole('group', { name: '显示列', exact: true });
  const groupHeader = desktop.getByRole('columnheader', { name: '组名', exact: true });
  await expect(groupHeader).toBeVisible();
  await expect(desktop.getByRole('cell', { name: '2026-11-18 07:28:58', exact: true })).toBeVisible();
  await expect(desktop.getByRole('cell', { name: '2026-11-18 07:28:59', exact: true })).toBeVisible();
  await trigger.click();
  await options.getByLabel('组名', { exact: true }).uncheck();
  await expect(groupHeader).toHaveCount(0);
  await expect(desktop.getByRole('button', { name: '详情', exact: true })).toBeVisible();

  await page.reload();
  await expect(desktop.getByRole('columnheader', { name: '任务名称', exact: true })).toBeVisible();
  await expect(groupHeader).toHaveCount(0);
  await trigger.click();
  await expect(options.getByLabel('组名', { exact: true })).not.toBeChecked();
  await trigger.click();

  await page.setViewportSize({ width: 390, height: 844 });
  const card = workspace.getByRole('button', { name: /执行记录示例.*详情/ });
  await expect(card).toContainText('成功');
  await expect(card).not.toContainText('验收组');
  await expect(card).toContainText('结束 2026-11-18 07:28:59');
  await expect(card).not.toContainText('.769494');
  await trigger.click();
  await options.getByLabel('组名', { exact: true }).check();
  await options.getByLabel('状态', { exact: true }).uncheck();
  await page.reload();
  await expect(card).toContainText('验收组');
  await expect(card).not.toContainText('成功');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  const detailRequest = page.waitForRequest(request => new URL(request.url()).pathname.endsWith('/taskLogDetail'));
  await card.click();
  await expect(page.getByRole('dialog')).toContainText('执行详情验收');
  expect(new URL((await detailRequest).url()).searchParams.get('end_time')).toBe(record.datetime);
  await page.keyboard.press('Escape');

  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(desktop.getByRole('columnheader', { name: '状态', exact: true })).toBeVisible();
  await expect(groupHeader).toHaveCount(0);
});

test('execution log date filters stay together with equal widths and reachable actions', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page, 'taskLogs');
  const form = page.locator('.filter-grid.logs');
  const shortcuts = page.locator('.log-shortcuts');
  const dateActions = shortcuts.getByRole('group', { name: '快捷日期范围' });
  const chips = page.getByRole('group', { name: '当前筛选', exact: true });
  const tools = page.locator('.log-results-tools');
  const loading = page.locator('.execution-records-pane .loading-status');
  await expect(form).toBeVisible();
  await dateActions.getByRole('button', { name: '最近 30 天', exact: true }).click();
  await expect(chips.getByRole('button', { name: '清除日期范围' })).toBeVisible();
  await expect(loading).toHaveAttribute('aria-busy', 'false');
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    const start = await box(form.locator('#task-log-start'));
    const end = await box(form.locator('#task-log-end'));
    const shortcutsBounds = await box(shortcuts);
    const dateActionBounds = await box(dateActions);
    const actions = await box(form.locator('.filter-actions'));
    const search = await box(form.getByRole('button', { name: '搜索', exact: true }));
    const clear = await box(form.getByRole('button', { name: '清空', exact: true }));
    const chip = await box(chips.getByRole('button', { name: '清除日期范围' }));
    const formBounds = await box(form);
    const toolsBounds = await box(tools);
    expect(Math.abs(start.width - end.width)).toBeLessThan(1);
    if (width > 350) {
      expect(Math.abs(start.y - end.y)).toBeLessThan(1);
      expect(end.x - start.x - start.width).toBeGreaterThanOrEqual(12);
    } else {
      expect(end.y).toBeGreaterThanOrEqual(start.y + start.height);
    }
    expect(dateActionBounds.y - shortcutsBounds.y).toBeGreaterThanOrEqual(10);
    expect(shortcutsBounds.y + shortcutsBounds.height - dateActionBounds.y - dateActionBounds.height).toBeGreaterThanOrEqual(10);
    expect(search.y - end.y - end.height).toBeGreaterThanOrEqual(14);
    expect(clear.x - search.x - search.width).toBeGreaterThanOrEqual(10);
    expect(chip.y - formBounds.y - formBounds.height).toBeGreaterThanOrEqual(10);
    expect(toolsBounds.y - chip.y - chip.height).toBeLessThanOrEqual(12);
    expect((await box(loading)).height).toBeLessThanOrEqual(4);
    for (const bounds of [start, end, actions, dateActionBounds, chip]) {
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
