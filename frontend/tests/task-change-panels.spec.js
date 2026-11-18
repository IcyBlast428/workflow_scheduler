import { test, expect } from '@playwright/test';

async function login(page, hash) {
  await page.goto('/#' + hash);
  await page.getByLabel('用户名', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}
async function pendingTask(page) {
  let reads = 0;
  await page.route('**/api/taskinfo/packages/gitlab', route => {
    reads++;
    return route.fulfill({ json: { code: 20000, data: { enabled: true, complete: true, checked_at: Date.now() / 1000, items: [
      { id: 'new-task', pid: 'new-task', kind: 'new', task_name: '新任务检查', group_name: 'mailPush', folder_name: 'original', sha: 'a'.repeat(40), file_count: 1, blocked: false },
    ] } } });
  });
  await page.route('**/api/admin/gitlab-updates/state*', route => route.fulfill({ json: { code: 20000, data: {
    enabled: true, scanning: false, checked_at: Date.now() / 1000, pending_merge: 0, pending_release: 0, count: 0,
    items: [], warnings: ['未设置平台部署基线，暂不比较平台已部署版本；任务发现与发布不受影响。'],
  } } }));
  return () => reads;
}

test('GitLab opens from the task footer without moving the list and restores focus', async ({ page }) => {
  const reads = await pendingTask(page);
  let scans = 0;
  await page.route('**/api/admin/gitlab-updates/scan', route => {
    scans++;
    return route.fulfill({ json: { code: 20000, data: { scanning: false } } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page, 'tasks');
  const footer = page.getByRole('region', { name: 'GitLab 任务变更', exact: true });
  const entry = footer.getByRole('button', { name: '查看连接与检查状态', exact: true });
  const dialog = page.getByRole('dialog', { name: 'GitLab 连接与检查状态', exact: true });
  const list = page.locator('.task-table');
  await expect(list).toBeVisible();
  await expect(footer.getByText('1 项待处理', { exact: true })).toBeVisible();
  await expect(entry).toHaveAttribute('aria-haspopup', 'dialog');
  await expect(dialog).toBeHidden();
  const rect = locator => locator.evaluate(element => {
    const { top, bottom } = element.getBoundingClientRect();
    return { top: top + scrollY, bottom: bottom + scrollY };
  });
  const initial = await rect(list);
  expect((await rect(footer)).top).toBeGreaterThan(initial.bottom);
  expect((await rect(footer)).bottom).toBeCloseTo(await page.evaluate(() => innerHeight + scrollY), 0);
  await entry.click();
  await expect(dialog).toBeFocused();
  await expect(dialog.getByRole('heading', { name: '新任务检查', exact: true })).toBeVisible();
  expect((await rect(list)).top).toBeCloseTo(initial.top, 0);
  await dialog.getByRole('button', { name: '立即检查 GitLab', exact: true }).click();
  await expect.poll(() => scans).toBe(1);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(entry).toBeFocused();
  const before = reads();
  await page.evaluate(() => window.dispatchEvent(new Event('wfs:task-releases-refresh')));
  await expect.poll(reads).toBeGreaterThan(before);
  await expect(dialog).toBeHidden();

  await page.setViewportSize({ width: 390, height: 844 });
  await entry.click();
  const box = await dialog.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  await dialog.getByRole('button', { name: '连接设置', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/#gitlab/);
});

test('GitLab footer stays at the viewport bottom and leaves pagination reachable', async ({ page }) => {
  await page.route('**/api/taskinfo/state?*', async route => {
    const response = await route.fetch();
    const payload = await response.json();
    const task = payload.data.items[0];
    payload.data.items = Array.from({ length: 20 }, (_, index) => ({
      ...task, id: `fixture_${index + 1}`, name: `示例任务 ${index + 1}`,
    }));
    payload.data.total = 25;
    await route.fulfill({ response, json: payload });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page, 'tasks');
  await expect(page.locator('.task-table tbody tr')).toHaveCount(20);
  const footer = page.getByRole('region', { name: 'GitLab 任务变更', exact: true });
  const pagination = page.locator('.pagination');
  const footerOffset = () => footer.evaluate(element => innerHeight - element.getBoundingClientRect().bottom);
  for (const [width, height] of [[1440, 900], [390, 844], [320, 700]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => scrollTo(0, 0));
    await expect.poll(footerOffset).toBeCloseTo(0, 0);
    await page.mouse.move(width - 45, height / 2);
    await page.mouse.wheel(0, 500);
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
    await expect.poll(footerOffset).toBeCloseTo(0, 0);
    await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
    await expect.poll(footerOffset).toBeCloseTo(0, 0);
    expect((await pagination.boundingBox()).y + (await pagination.boundingBox()).height)
      .toBeLessThan((await footer.boundingBox()).y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
});

test('empty version differences explain new-task publication and link to the task footer', async ({ page }) => {
  await pendingTask(page);
  await login(page, 'gitlab');
  await expect(page.getByRole('heading', { name: '暂无可比较的版本差异', exact: true })).toBeVisible();
  await expect(page.locator('.gitlab-empty')).toContainText('新任务请到任务列表审查发布');
  await page.getByRole('button', { name: '任务待处理 1 · 前往任务列表', exact: true }).click();
  await expect(page).toHaveURL(/#tasks/);
  const footer = page.getByRole('region', { name: 'GitLab 任务变更', exact: true });
  await expect(footer.getByText('1 项待处理', { exact: true })).toBeVisible();
  await footer.getByRole('button', { name: '查看连接与检查状态', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'GitLab 连接与检查状态', exact: true }).locator('.new-task-card')).toContainText('新任务检查');
});

test('recent results default to ten and remember a changed count after reload', async ({ page }) => {
  await page.route('**/api/taskinfo/matrix-recent*', route => route.fulfill({ json: { code: 20000, data: {
    limit: Number(new URL(route.request().url()).searchParams.get('limit')), tasks: [{ pid: 'example', name: '示例', group: '测试', records: [] }],
  } } }));
  await login(page, 'matrix');
  const count = page.getByRole('combobox', { name: '执行次数', exact: true });
  await expect(count).toHaveValue('10');
  await expect(page.locator('.recent-cell')).toHaveCount(10);
  await count.selectOption('25');
  await expect(page.locator('.recent-cell')).toHaveCount(25);
  await page.reload();
  await expect(count).toHaveValue('25');
  await expect(page.locator('.recent-cell')).toHaveCount(25);
});
