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

test('pending changes really collapse and remain hidden after a refresh', async ({ page }) => {
  const reads = await pendingTask(page);
  await login(page, 'tasks');
  const panel = page.getByRole('region', { name: 'GitLab 任务变更', exact: true });
  const content = panel.locator('.changes-content');
  await expect(content).toBeVisible();
  await panel.getByRole('button', { name: '收起', exact: true }).click();
  await expect(content).toBeHidden();
  await expect(panel.getByRole('button', { name: '查看待处理变更', exact: true })).toHaveAttribute('aria-expanded', 'false');
  const before = reads();
  await page.evaluate(() => window.dispatchEvent(new Event('wfs:task-releases-refresh')));
  await expect.poll(reads).toBeGreaterThan(before);
  await expect(content).toBeHidden();
  await panel.getByRole('button', { name: '查看待处理变更', exact: true }).click();
  await expect(content).toBeVisible();
  await expect(panel.getByRole('button', { name: '收起', exact: true })).toHaveAttribute('aria-expanded', 'true');
});

test('empty version differences explain new-task publication and link to its card', async ({ page }) => {
  await pendingTask(page);
  await login(page, 'gitlab');
  await expect(page.getByRole('heading', { name: '暂无可比较的版本差异', exact: true })).toBeVisible();
  await expect(page.locator('.gitlab-empty')).toContainText('新任务请到任务列表审查发布');
  await page.getByRole('button', { name: '任务待处理 1 · 前往任务列表', exact: true }).click();
  await expect(page).toHaveURL(/#tasks/);
  await expect(page.locator('.new-task-card')).toContainText('新任务检查');
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
