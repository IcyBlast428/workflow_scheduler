import {test,expect} from '@playwright/test';

async function login(page,hash='admin?section=connections'){
  await page.goto('/#'+hash);
  await page.getByLabel('用户名',{exact:true}).fill('admin');
  await page.getByLabel('密码',{exact:true}).fill('browser-test-password');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}

test('business connections use a searchable inventory and type-specific NewDB settings',async({page})=>{
  await login(page);
  const pane=page.locator('.connection-panel');
  await expect(pane.locator('.connection-table')).toBeVisible();
  await expect(pane.getByLabel('数据库类型',{exact:true}).locator('option')).toHaveCount(6);
  await pane.getByLabel('查找业务连接').fill('no_such_connection');
  await expect(pane.locator('.connection-table')).toContainText('没有匹配的连接');
  await pane.getByLabel('查找业务连接').clear();
  await pane.getByLabel('连接标识',{exact:true}).fill('future_reporting');
  await pane.getByLabel('数据库类型',{exact:true}).selectOption('oracle');
  await expect(pane.getByLabel('服务名（Service Name）')).toBeVisible();
  await expect(pane.locator('.connection-example')).toContainText('SELECT 1 FROM dual');
  await pane.getByLabel('数据库类型',{exact:true}).selectOption('gaussdb');
  await expect(pane.getByLabel('ODBC 驱动名称',{exact:false})).toHaveValue('DWS');
  const tls=pane.getByLabel('连接加密',{exact:false});
  await expect(tls.locator('option')).toHaveCount(2);
  await tls.selectOption('require');
  await expect(pane.getByLabel('服务器 CA 证书路径')).toHaveCount(0);
  await pane.getByRole('button',{name:'平台数据库',exact:true}).click();
  await expect(pane.locator('.platform-database')).toBeVisible();
  await pane.getByRole('button',{name:/业务数据库 ·/}).click();
  await expect(pane.getByLabel('连接标识',{exact:true})).toHaveValue('future_reporting');
  await pane.getByText('连接池设置',{exact:true}).click();
  await expect(pane.getByLabel('常驻连接上限',{exact:true})).toHaveValue('1');
  await expect(pane.getByLabel('临时额外连接上限',{exact:true})).toHaveValue('1');
});

test('staged platform settings preserve active identity and hide saved passwords',async({page})=>{
  const initial={revision:0,source:'service',driver:'DWS',db_id:'scheduler_wfs',host:'',port:8000,database:'',schema:'wfs',user:'',password_set:false,web_pool_size:5,web_max_overflow:3,scheduler_pool_size:10,scheduler_max_overflow:5,pool_timeout:10,pool_recycle:600,connect_timeout:10,query_timeout:10};
  let stored={...initial},posted;
  await page.route('**/api/admin/platform-database',route=>route.fulfill({json:{status:'success',code:20000,data:{active:initial,saved:stored,restart_required:stored.revision>0,drivers:['DWS'],diagnostics:{processes:[],metrics:{}}}}}));
  await page.route('**/api/admin/platform-database/save',async route=>{
    posted=route.request().postDataJSON();
    const {password,...safe}=posted;stored={...safe,revision:1,password_set:true};
    await route.fulfill({json:{status:'success',code:20000,data:{profile:stored,restart_required:true,ready:true}}});
  });
  await login(page);await page.getByRole('button',{name:'平台数据库',exact:true}).click();
  const pane=page.locator('.platform-database');
  await pane.getByRole('combobox',{name:'配置来源',exact:true}).selectOption('direct');
  await pane.getByLabel('平台数据库地址').fill('database.example.internal');
  await pane.getByLabel('平台数据库名称').fill('workflow');
  await pane.getByLabel('平台数据库账号').fill('scheduler');
  await pane.getByLabel('平台数据库密码').fill('test-only-not-a-real-secret');
  await pane.getByRole('button',{name:'测试并保存待重启配置'}).click();
  await page.locator('.confirm-modal').getByRole('button',{name:'测试并保存',exact:true}).click();
  await expect(pane.getByRole('status')).toContainText('完整重启服务后生效');
  await expect(pane).toContainText('已有版本 1 的待生效配置');
  await expect(pane).toContainText('当前版本 0');
  await expect(pane.getByLabel('平台数据库密码')).toHaveValue('');
  expect(posted.password).toBe('test-only-not-a-real-secret');
  expect(await pane.innerText()).not.toContain('test-only-not-a-real-secret');
});

test('history policy persists bounds and makes same-database archival explicit',async({page})=>{
  await login(page,'admin?section=storage');
  const pane=page.locator('.history-storage-policy');
  await expect(pane.getByLabel('成功执行摘要上限（KiB）',{exact:false})).toHaveValue('2');
  await pane.getByLabel('成功执行摘要上限（KiB）',{exact:false}).fill('1');
  await pane.getByLabel('启用历史自动归档').check();
  await expect(pane).toContainText('不释放数据库总空间');
  await pane.getByLabel('每批归档上限（条）',{exact:true}).fill('100');
  await pane.getByRole('button',{name:'保存历史存储策略'}).click();
  await expect(pane.getByRole('status')).toContainText('已保存');
  await page.reload();
  await expect(pane.getByLabel('成功执行摘要上限（KiB）',{exact:false})).toHaveValue('1');
  await expect(pane.getByLabel('启用历史自动归档')).toBeChecked();
  await expect(pane.getByLabel('每批归档上限（条）',{exact:true})).toHaveValue('100');
  await pane.getByLabel('启用历史自动归档').uncheck();
  await pane.getByLabel('成功执行摘要上限（KiB）',{exact:false}).fill('2');
  await pane.getByRole('button',{name:'保存历史存储策略'}).click();
  await expect(pane.getByRole('status')).toContainText('已保存');
});

test('connection and storage forms fit desktop and narrow screens',async({page})=>{
  await login(page);
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:1000});
    await page.getByRole('button',{name:'平台数据库',exact:true}).click();
    const pane=page.locator('.platform-database');
    await expect(pane.getByRole('button',{name:'测试平台连接'})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    if(width===1440)await page.screenshot({path:'/tmp/wfs-platform-database-desktop.png',fullPage:true});
    await page.getByRole('button',{name:/业务数据库 ·/}).click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    if(width===320)await page.screenshot({path:'/tmp/wfs-business-database-mobile.png',fullPage:true});
  }
  await page.getByRole('button',{name:'审计与存储',exact:true}).click();
  await page.getByRole('button',{name:'存储清理与备份',exact:true}).click();
  await expect(page.locator('.history-storage-policy')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
