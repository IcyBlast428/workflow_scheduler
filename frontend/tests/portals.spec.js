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
    await expect(page.getByRole('navigation',{name:'工作区导航'}).getByRole('button')).toHaveText(['任务列表','任务执行']);
    for (const label of ['数据库连接','系统管理','任务示例','依赖仓库','总览','平台事件','手动执行','检查更新','批量暂停调度'])
      await expect(page.getByRole('button', {name:label,exact:true})).toHaveCount(0);
    const row = page.locator('.task-table tbody tr').filter({hasText:'acceptance__slow'});
    await row.getByRole('button', {name:'更多',exact:true}).click();
    await expect(page.locator('.action-menu').getByRole('button')).toHaveText(['任务详情','最新输出', /收藏/]);
    await page.keyboard.press('Escape');
    await row.locator('.task-name-link').click();
    await expect(page.getByRole('dialog').getByRole('navigation',{name:'任务工作区'}).getByRole('button')).toHaveText(['概览','执行']);
    await expect(page.getByRole('dialog').getByRole('tab')).toHaveText(['说明与配置']);
    expect(requests.filter(path => path.startsWith('/api/admin') || path === '/api/taskinfo/dashboard')).toEqual([]);
    expect((await page.request.get('/api/admin/database-connections')).status()).toBe(403);
    expect((await page.request.get('/api/taskinfo/source?pid=acceptance__slow')).status()).toBe(403);
    await page.goto('/admin/#connections');
    await expect(page).toHaveURL(/\/viewer\/#tasks/);
  });
}

test('the same login page detects an ordinary account even at an administrator URL', async ({page}) => {
  await page.goto('/admin/#dashboard');
  await expect(page.getByRole('heading',{name:'登录工作区',exact:true})).toBeVisible();
  await expect(page.locator('.login-tagline, .login-workflow-line')).toHaveCount(0);
  await expect(page.getByRole('link', {name:'管理员入口 →'})).toHaveCount(0);
  await page.screenshot({path:'../data/unified-login.jpg',fullPage:true});
  await login(page, 'browser-viewer', '/admin/#dashboard');
  await expect(page.locator('.app-shell')).toBeVisible();
  await expect(page).toHaveURL(/\/viewer\/#tasks/);
  expect((await page.request.get('/api/admin/database-connections')).status()).toBe(403);
});

test('business profile failures preserve masked passwords',async({page})=>{
 let saved=false;
 const profile={id:'mysql_orders',dialect:'mysql',host:'db.example.com',port:3306,database:'orders',user:'wfs',tls:'disabled',password_set:true,revision:1};
 const types=[{dialect:'mysql',label:'MySQL / PolarDB / MariaDB',port:3306,available:true}];
 await page.route('**/api/admin/database-connections',r=>r.fulfill({json:{code:20000,data:{active_dialect:'GaussDB / DWS',profiles:saved?[profile]:[],supported_databases:types}}}));
 await page.route('**/api/admin/database-connections/test',r=>r.fulfill({status:400,json:{code:100,message:'模拟连接失败',data:{}}}));
 await page.route('**/api/admin/database-connections/save',async r=>{expect(r.request().postDataJSON().password).toBe(saved?'':'disposable-test-password');saved=true;await r.fulfill({json:{code:20000,data:{profile}}});});
 await login(page,'admin','/admin/#connections');await expect(page.locator('.connection-panel')).toBeVisible();
 await page.getByLabel('连接标识',{exact:true}).fill(profile.id);await page.getByLabel('数据库类型',{exact:true}).selectOption('mysql');
 await page.getByLabel('数据库地址',{exact:true}).fill(profile.host);await page.getByLabel('数据库名称',{exact:true}).fill(profile.database);
 await page.getByLabel('数据库用户名',{exact:true}).fill(profile.user);await page.getByLabel('数据库密码',{exact:true}).fill('disposable-test-password');
 await page.getByRole('button',{name:'测试连接',exact:true}).click();await expect(page.getByRole('alert')).toContainText('模拟连接失败');
 await page.getByRole('button',{name:'测试并保存',exact:true}).click();await expect(page.locator('.connection-panel').getByRole('status')).toContainText('业务连接已保存');
 await expect(page.getByLabel('数据库密码',{exact:true})).toHaveValue('');await expect(page.getByLabel('连接标识',{exact:true})).toHaveAttribute('readonly','');
 await page.getByRole('button',{name:'测试并保存',exact:true}).click();await expect(page.locator('.connection-panel').getByRole('status')).toContainText('业务连接已保存');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('supported types and real PostgreSQL pool settings persist',async({page})=>{
 await login(page,'admin','/admin/#connections');await page.getByRole('button',{name:/pg_browser/}).click();
 await expect(page.getByLabel('数据库类型',{exact:true}).locator('option')).toHaveText(['MySQL / PolarDB / MariaDB','PostgreSQL / GaussDB','ClickHouse']);
 await expect(page.getByLabel('数据库类型',{exact:true})).toHaveValue('postgresql');await page.getByText('连接池设置',{exact:true}).click();
 await expect(page.getByLabel('常驻连接上限',{exact:true})).toHaveValue('2');await page.getByRole('button',{name:'测试并保存',exact:true}).click();
 await expect(page.locator('.connection-panel').getByRole('status')).toContainText('业务连接已保存');await page.reload();await page.getByRole('button',{name:/pg_browser/}).click();
 await page.getByText('连接池设置',{exact:true}).click();await expect(page.getByLabel('常驻连接上限',{exact:true})).toHaveValue('2');
});
