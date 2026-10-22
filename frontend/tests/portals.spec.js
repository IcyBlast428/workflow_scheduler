import { test, expect } from '@playwright/test';

async function login(page, username, path) {
  await page.goto(path);
  await page.getByLabel('用户名', {exact: true}).fill(username);
  await page.getByLabel('密码', {exact: true}).fill('browser-test-password');
  await page.getByRole('button', {name:'登录', exact:true}).click();
}

for (const username of ['browser-viewer','browser-operator']) {
  test(`${username} has a separate read-only task workspace and protected deep links`, async ({page}) => {
    const requests = [];
    page.on('request', request => requests.push(new URL(request.url()).pathname));
    await login(page, username, '/viewer/#admin');
    await expect(page.locator('.app-shell')).toBeVisible();
    await expect(page).toHaveURL(/\/viewer\/#tasks/);
    await expect(page.getByRole('navigation').getByRole('button')).toHaveCount(3);
    for (const label of ['数据库连接','账户与审计','任务发布','总览','平台事件','手动执行','检查更新','批量暂停调度'])
      await expect(page.getByRole('button', {name:label,exact:true})).toHaveCount(0);
    const row = page.locator('.task-table tbody tr').filter({hasText:'acceptance__slow'});
    await row.getByRole('button', {name:'更多',exact:true}).click();
    await expect(page.locator('.action-menu').getByRole('button')).toHaveText(['最新输出']);
    await page.keyboard.press('Escape');
    await row.getByRole('button', {name:'详情',exact:true}).click();
    await expect(page.getByRole('dialog').getByRole('tab')).toHaveText(['说明与配置','执行记录']);
    expect(requests.filter(path => path.startsWith('/api/admin') || path === '/api/taskinfo/dashboard')).toEqual([]);
    expect((await page.request.get('/api/admin/database-connections')).status()).toBe(403);
    expect((await page.request.get('/api/taskinfo/source?pid=acceptance__slow')).status()).toBe(403);
    await page.goto('/admin/#connections');
    await expect(page).toHaveURL(/\/viewer\/#tasks/);
  });
}

test('ordinary accounts cannot log in through the administrator entry', async ({page}) => {
  await login(page, 'browser-viewer', '/admin/#dashboard');
  await expect(page.locator('.toast-root')).toContainText('用户名或密码错误');
  await expect(page.locator('.app-shell')).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'管理员登录',exact:true})).toBeVisible();
});

test('database settings switch scopes, report test failures and preserve masked passwords', async ({page}) => {
  let saved = false;
  const profile = {id:'mysql_orders',host:'db.example.com',port:3306,database:'orders',user:'wfs',tls:'disabled',ssl_ca:'',password_set:true,revision:1};
  await page.route('**/api/admin/database-connections', route => route.fulfill({json:{code:20000,data:{active_dialect:'SQLite',profiles:saved?[profile]:[],active:null,restart_required:false}}}));
  await page.route('**/api/admin/database-connections/test', route => route.fulfill({status:400,json:{code:100,message:'模拟连接失败，请核对连接信息。',data:{}}}));
  await page.route('**/api/admin/database-connections/save', async route => {
    const body = route.request().postDataJSON();
    expect(body.id).toBe('mysql_orders');
    expect(body.password).toBe(saved?'':'disposable-test-password');
    saved = true;
    await route.fulfill({json:{code:20000,data:{connected:true,ready:true,version:'8.4.test',database:'orders',missing:[],profile}}});
  });
  await login(page, 'admin', '/admin/#connections');
  await expect(page.locator('.connection-panel')).toBeVisible();
  await expect(page.getByLabel('连接标识',{exact:true})).toHaveValue('platform');
  await page.getByRole('button',{name:'任务业务数据库',exact:true}).click();
  await expect(page.getByLabel('连接标识',{exact:true})).toBeEditable();
  await page.getByLabel('连接标识',{exact:true}).fill('mysql_orders');
  await page.getByLabel('数据库地址',{exact:true}).fill(profile.host);
  await page.getByLabel('数据库名称',{exact:true}).fill(profile.database);
  await page.getByLabel('数据库用户名',{exact:true}).fill(profile.user);
  await page.getByLabel('数据库密码',{exact:true}).fill('disposable-test-password');
  await page.getByLabel('连接加密',{exact:true}).selectOption('disabled');
  await page.getByRole('button',{name:'测试连接',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('模拟连接失败');
  await page.getByRole('button',{name:'测试并保存',exact:true}).click();
  await expect(page.getByText('业务连接已保存，任务下次建立连接时生效。')).toBeVisible();
  await expect(page.getByLabel('数据库密码',{exact:true})).toHaveValue('');
  await page.getByRole('button',{name:'测试并保存',exact:true}).click();
  await expect(page.getByText('业务连接已保存，任务下次建立连接时生效。')).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
