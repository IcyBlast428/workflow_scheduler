import { test, expect } from '@playwright/test';

async function login(page, username = 'admin', hash = 'tasks') {
  await page.goto('/#' + hash);
  await page.getByLabel('用户名', { exact: true }).fill(username);
  await page.getByLabel('密码', { exact: true }).fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}

test('login reminder opens real GitLab diff review, read state persists and mobile layout fits', async ({ page }) => {
  const faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await login(page);
  await expect(page.locator('.gitlab-reminder')).toContainText('待合并 1 项');
  await page.getByRole('button', { name: '查看代码差异', exact: true }).click();
  await expect(page).toHaveURL(/#gitlab$/);
  await expect(page.locator('.gitlab-update-row')).toHaveCount(3);
  await expect(page.getByLabel('代码差异审查')).toContainText('待合并：feature/report');
  await expect(page.getByLabel('文件差异')).toContainText('+new-platform');
  await expect(page.getByRole('link', { name: '去 GitLab 查看合并请求' })).toHaveAttribute('href', /source_branch=feature%2Freport/);
  await expect(page.getByRole('link', { name: '在 GitLab 查看完整差异' })).toHaveAttribute('href', new RegExp('b{40}\\.\\.\\.c{40}'));
  await page.getByLabel('修改文件').getByRole('button').filter({ hasText: 'app/jobs/acceptance/slow/main.py' }).click();
  await expect(page.getByLabel('文件差异')).toContainText('+new-task');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: '../data/gitlab-review-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel('文件差异')).toContainText('+new-task');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '../data/gitlab-review-mobile.png', fullPage: true });
  await page.getByRole('button', { name: '标记本批已读', exact: true }).click();
  await expect(page.getByRole('button', { name: '标记本批已读', exact: true })).toHaveCount(0);
  await page.goto('/admin/#tasks');
  await expect(page.locator('.app-shell')).toBeVisible();
  await expect(page.locator('.gitlab-reminder')).toHaveCount(0);
  expect(faults).toEqual([]);
});

test('configuration masks the token, validates relative directories and saves with CSRF', async ({ page }) => {
  await login(page, 'admin', 'gitlab');
  const details = page.locator('.gitlab-settings');
  await details.locator('summary').click();
  await expect(page.getByLabel('只读访问令牌', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('只读访问令牌', { exact: true })).toHaveAttribute('placeholder', '已保存，留空保留');
  await page.getByLabel('任务代码根目录（每行一项）').fill('../jobs');
  await page.getByRole('button', { name: '保存 GitLab 设置', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('目录必须');
  await page.getByLabel('任务代码根目录（每行一项）').fill('app/jobs');
  await page.getByRole('button', { name: '保存 GitLab 设置', exact: true }).click();
  await expect(page.locator('.gitlab-workspace').getByRole('status')).toContainText('设置已保存');
  await page.getByRole('button', { name: '立即检查', exact: true }).click();
  await expect(page.locator('.gitlab-update-row')).toHaveCount(3);
  expect((await page.request.get('/api/admin/gitlab-updates/configuration')).status()).toBe(200);
});

test('ordinary users receive neither code reminders nor protected GitLab data', async ({ page }) => {
  const protectedCalls = [];
  page.on('request', request => { if (request.url().includes('/api/admin/gitlab-updates')) protectedCalls.push(request.url()); });
  await login(page, 'browser-viewer', 'gitlab');
  await expect(page).toHaveURL(/\/viewer\/#tasks/);
  await expect(page.locator('.gitlab-reminder')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /代码更新/ })).toHaveCount(0);
  expect(protectedCalls).toEqual([]);
  expect((await page.request.get('/api/admin/gitlab-updates/state')).status()).toBe(403);
});
