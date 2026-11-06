import {test, expect} from '@playwright/test';
async function login(page, hash = 'tasks') {
  await page.goto('/#' + hash);
  await page.getByLabel('用户名', {exact:true}).fill('admin');
  await page.getByLabel('密码', {exact:true}).fill('browser-test-password');
  await page.getByRole('button', {name:'登录', exact:true}).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}

test('description renders Markdown safely and metadata remains readable on mobile', async ({page}) => {
  await page.route('**/api/taskinfo/detail?*', async route => {
    const response = await route.fetch(), body = await response.json();
    body.data.schedule.form.description = '# 输出说明\n\n- 生成 `report.csv`\n- **保留历史**\n\n```python\nprint("done")\n```\n\n[危险链接](javascript:alert(1))\n\n<img src="/unexpected-image" onerror="window.markdownUnsafe=true"><script>window.markdownUnsafe=true</script><iframe src="/">坏内容</iframe>';
    body.data.schedule.updated_at = '2026-11-05 08:52:29.546499';
    await route.fulfill({json:body});
  });
  await login(page);
  await page.locator('.task-table tbody tr').filter({hasText:'acceptance__slow'}).locator('.task-name-link').click();
  const document = page.locator('.markdown-content');
  await expect(document.getByRole('heading', {name:'输出说明'})).toBeVisible();
  await expect(document.locator('li')).toHaveCount(2);
  await expect(document.locator('pre code')).toContainText('print("done")');
  await expect(document.locator('.hljs-built_in')).toHaveCount(1);
  await expect(document.locator('script,img,iframe,[onerror],a[href^="javascript:"]')).toHaveCount(0);
  expect(await page.evaluate(() => window.markdownUnsafe)).toBeUndefined();
  const metadata = page.getByLabel('任务配置信息');
  await expect(metadata).toContainText('2026-11-05 08:52:29');
  await expect(metadata).not.toContainText('.546499');
  await expect(metadata.locator('[title="2026-11-05 08:52:29.546499"]')).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:'test-results/ui-polish-description-mobile.png',fullPage:true});
});

test('task filters remain compact and maintenance controls can be expanded', async ({page}) => {
  await page.setViewportSize({width:1440,height:1000});
  await login(page);
  await expect(page.locator('.page-title strong')).toHaveText('任务列表');
  await expect(page.locator('.panel-head h2').filter({hasText:'任务列表'})).toHaveCount(0);
  const panel=page.getByLabel('执行维护模式');
  await expect(panel.getByRole('button',{name:'进入维护',exact:true})).not.toBeVisible();
  await panel.getByRole('button',{name:'维护操作',exact:true}).click();
  await expect(panel.getByRole('button',{name:'进入维护',exact:true})).toBeVisible();
  await panel.getByRole('button',{name:'收起维护',exact:true}).click();
  await expect(page.locator('.task-table')).toBeVisible();
  expect((await page.locator('.task-table').boundingBox()).y).toBeLessThan(450);
  await page.screenshot({path:'test-results/ui-polish-task-list.png',fullPage:true});
});

test('no failures uses full width for recent execution while failures stay visible', async ({page}) => {
  let failures=[];
  await page.route('**/api/taskinfo/dashboard*', async route => {
    const response=await route.fetch(), body=await response.json();
    body.data.failure_rank=failures;
    body.data.recent_runs=[{id:'acceptance__slow',name:'测试执行',state:0,start_time:'2026-11-05 08:52:23.000000',end_time:'2026-11-05 08:52:24.546499'}];
    await route.fulfill({json:body});
  });
  await login(page,'dashboard');
  await expect(page.locator('.issue-columns')).toHaveClass(/recent-only/);
  await expect(page.locator('.recent-run-copy')).toContainText('2026-11-05 08:52:24');
  await expect(page.locator('.recent-run-copy')).not.toContainText('.546499');
  failures=[{id:'acceptance__slow',name:'需要处理的任务',count:2}];
  await page.reload();
  await expect(page.locator('.issue-columns')).not.toHaveClass(/recent-only/);
  await expect(page.getByRole('button',{name:'需要处理的任务 2 次'})).toBeVisible();
});
