import { test, expect } from '@playwright/test';

test('task examples replace ZIP uploads and repository settings have their own navigation', async ({page}) => {
  await page.goto('/#packages');
  await page.getByLabel('用户名', {exact:true}).fill('admin');
  await page.getByLabel('密码', {exact:true}).fill('browser-test-password');
  await page.getByRole('button', {name:'登录',exact:true}).click();
  await expect(page.locator('.task-examples')).toBeVisible();
  await expect(page.getByRole('heading', {name:'任务示例',exact:true})).toBeVisible();
  await expect(page.locator('input[type=file]')).toHaveCount(0);
  await expect(page.locator('.repository-settings')).toHaveCount(0);
  await page.getByRole('button', {name:'依赖仓库',exact:true}).click();
  await expect(page).toHaveURL(/#repository$/);
  await expect(page.getByLabel('依赖安装方式')).toBeVisible();
  await page.getByRole('button', {name:'任务列表',exact:true}).click();
  await expect(page.getByLabel('GitLab 任务变更')).toContainText('配置 GitLab');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
