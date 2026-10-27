import { test, expect } from '@playwright/test';

test('GitLab task discovery, publication, marked updates and confirmed deletion', async ({page}) => {
  test.setTimeout(100000);
  const faults = []; page.on('pageerror', error => faults.push(error.message));
  await page.goto('/#tasks');
  await page.getByLabel('用户名', {exact:true}).fill('admin');
  await page.getByLabel('密码', {exact:true}).fill('browser-test-password');
  await page.getByRole('button', {name:'登录',exact:true}).click();
  const card = page.locator('.new-task-card').filter({hasText:'GitLab new report'});
  await expect(card).toContainText('GitLab 新任务');
  await page.screenshot({path:'../data/gitlab-task-new.png',fullPage:true});
  await card.getByRole('button', {name:'审查并发布',exact:true}).click();
  const dialog = page.getByRole('dialog', {name:'任务代码版本',exact:true});
  await dialog.getByRole('button', {name:'获取 GitLab 版本并查看差异',exact:true}).click();
  await expect(dialog.getByLabel('发布版本预览')).toContainText('新增 2');
  await dialog.getByRole('button', {name:'新增 helper.py',exact:true}).click();
  await expect(dialog.locator('.release-code')).toContainText('+value="GITLAB_V1"');
  const publish = async () => {
    await dialog.getByRole('button', {name:'检查依赖环境',exact:true}).click();
    await expect(dialog.getByRole('button', {name:'发布此版本',exact:true})).toBeVisible({timeout:35000});
    await dialog.getByRole('button', {name:'发布此版本',exact:true}).click();
    await page.locator('.confirm-modal').getByRole('button', {name:'确认发布',exact:true}).click();
    await expect(dialog.getByRole('status')).toContainText('任务代码已发布');
  };
  await publish();
  await dialog.getByRole('button', {name:'关闭',exact:true}).click();
  const row = page.locator('.task-table tbody tr').filter({hasText:'git_new'});
  await expect(row).toContainText('未配置');
  await row.getByRole('button', {name:'手动执行',exact:true}).click();
  await expect(page.locator('.execution-output')).toContainText('GITLAB_V1');
  await page.locator('.execution-modal').getByTitle('关闭').click();
  const headers = {'X-CSRF-Token': await page.evaluate(() => sessionStorage.getItem('wfs_csrf_token'))};
  const change = async action => {
    expect((await page.request.post('/api/admin/fixture/gitlab', {headers,data:{action}})).status()).toBe(200);
    await page.getByRole('button', {name:'刷新变更',exact:true}).click();
  };
  try {
    await change('update');
    await expect(row.locator('.task-change-badge')).toContainText('GitLab 有更新');
    await row.locator('.task-change-badge').click();
    await dialog.getByRole('button', {name:'获取 GitLab 版本并查看差异',exact:true}).click();
    await dialog.getByRole('button', {name:'修改 helper.py',exact:true}).click();
    await expect(dialog.locator('.release-code')).toContainText('+value="GITLAB_V2"');
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path:'../data/gitlab-task-release-mobile.png',fullPage:true});
    await page.setViewportSize({width:1440,height:1000});
    await publish();
    await dialog.getByRole('button', {name:'关闭',exact:true}).click();
    await change('delete');
    await expect(row.locator('.task-change-badge')).toContainText('GitLab 已删除');
    await row.locator('.task-change-badge').click();
    await dialog.getByRole('button', {name:'确认删除任务',exact:true}).click();
    await page.locator('.confirm-modal').getByRole('button', {name:'确认删除',exact:true}).click();
    await expect(dialog.getByRole('status')).toContainText('输出文件已保留');
    await dialog.getByRole('button', {name:'关闭',exact:true}).click();
    await expect(row).toHaveCount(0);
  } finally { await page.request.post('/api/admin/fixture/gitlab', {headers,data:{action:'reset'}}); }
  expect(faults).toEqual([]);
});
