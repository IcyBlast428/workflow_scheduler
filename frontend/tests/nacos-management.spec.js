import {test,expect} from '@playwright/test';

const respond=(route,data)=>route.fulfill({json:{status:'success',code:20000,data}});
const binding={namespace:'',group:'DEFAULT_GROUP',data_id:'reports-db.json',password_encoding:'plain',fields:{host:'host',port:'port',database:'db',user:'user',password:'password',schema:'schema'}};
const nacosProfile={revision:1,url:'http://nacos.example.internal:8848/nacos',username:'config-admin',password_set:true,auth_enabled:true,verify_tls:true,ca_file:'',timeout:10,config_ttl:30};
const databaseProfile={id:'reports',name:'报表库',source:'nacos',nacos:binding,revision:1,dialect:'postgresql',host:'db.internal',port:5432,database:'reports',user:'reader',password_set:true,enabled:true,pool_enabled:true,pool_size:1,max_overflow:1,pool_timeout:10,pool_recycle:600,tls:'disabled',driver:''};
const platformProfile={revision:0,source:'service',driver:'DWS',db_id:'scheduler_wfs',host:'',port:8000,database:'',schema:'wfs',user:'',password_set:false,web_pool_size:5,web_max_overflow:3,scheduler_pool_size:10,scheduler_max_overflow:5,pool_timeout:10,pool_recycle:600,connect_timeout:10,query_timeout:10};
async function login(page){await page.goto('/#admin?section=connections');await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();}
async function inventory(page,profiles=[],canManage=true){await page.route('**/api/admin/database-connections',route=>respond(route,{profiles,can_manage_nacos:canManage,supported_databases:[{dialect:'postgresql',label:'PostgreSQL',package:'psycopg2',available:true,driver_ready:true,port:5432,tls_modes:['disabled','verify_identity']}]}));await page.route('**/api/admin/operational/connections',route=>respond(route,[]));}
async function preview(page,onRead=()=>{}){await page.route('**/api/admin/nacos/preview',route=>{const input=route.request().postDataJSON();onRead(input);return respond(route,{profile:{host:'loaded-db.internal',port:5432,database:'reports',user:'reader',schema:'wfs',password_set:true},md5:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',nacos_settings_token:'nacos-settings-version-a',binding:input.binding});});}

test('Nacos business configuration requires a fresh read and confirms shared publication',async({page})=>{
  await inventory(page);let reads=0,posted;
  await preview(page,()=>reads++);
  await page.route('**/api/admin/database-connections/save',route=>{posted=route.request().postDataJSON();return respond(route,{profile:{...databaseProfile,...posted,password:undefined,password_set:true,revision:1},nacos_synced:true,md5:'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'});});
  await login(page);const pane=page.locator('.connection-body');
  await pane.getByLabel('连接标识',{exact:true}).fill('reports');
  await pane.getByLabel('业务配置来源').selectOption('nacos');
  await pane.getByLabel('配置 Data ID').fill('reports-db.json');
  const save=pane.getByRole('button',{name:'测试并保存',exact:true});
  await expect(save).toBeDisabled();
  await pane.getByRole('button',{name:'读取 Nacos 配置',exact:true}).click();
  await expect(pane.getByLabel('数据库地址',{exact:true})).toHaveValue('loaded-db.internal');
  await expect(pane.getByLabel('数据库密码',{exact:true})).toHaveValue('');
  await expect(save).toBeEnabled();
  await pane.getByLabel('配置分组').fill('REPORTS_GROUP');
  await expect(save).toBeDisabled();
  await pane.getByRole('button',{name:'读取 Nacos 配置',exact:true}).click();
  await pane.getByText('字段映射与密码编码',{exact:true}).click();
  await pane.getByLabel('数据库名称对应字段').fill('database');
  await expect(save).toBeDisabled();
  await pane.getByRole('button',{name:'读取 Nacos 配置',exact:true}).click();
  await pane.getByLabel('数据库地址',{exact:true}).fill('new-db.internal');
  await save.click();
  const confirm=page.locator('.confirm-modal');await expect(confirm).toContainText('其他消费者也会读到修改');
  await confirm.getByRole('button',{name:'测试并同步保存'}).click();
  await expect(pane.getByRole('status')).toContainText('已同步至 Nacos');
  expect(reads).toBe(3);expect(posted.nacos_md5).toBe('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');expect(posted.nacos_settings_token).toBe('nacos-settings-version-a');expect(posted.nacos.fields.database).toBe('database');expect(posted.host).toBe('new-db.internal');expect(posted.password).toBe('');
  await expect(save).toBeDisabled();
});

test('other administrators only view Nacos-backed connections and Nacos settings',async({page})=>{
  await inventory(page,[databaseProfile],false);let remoteRequests=0;
  await page.route('**/api/admin/nacos/preview',route=>{remoteRequests++;return respond(route,{});});
  await page.route('**/api/admin/nacos',route=>respond(route,{profile:nacosProfile,configured:true,can_edit:false,editor_username:'admin'}));
  await login(page);const business=page.locator('.connection-body');
  await business.getByRole('button',{name:'编辑 reports'}).click();
  await expect(business).toContainText('此连接来自 Nacos，当前账号仅可查看');
  await expect(business.getByLabel('业务配置来源')).toBeDisabled();
  await expect(business.getByLabel('数据库地址',{exact:true})).toBeDisabled();
  await expect(business.getByRole('button',{name:'读取 Nacos 配置',exact:true})).toHaveCount(0);
  await expect(business.getByRole('button',{name:'测试并保存',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Nacos 连接',exact:true}).click();const settings=page.locator('.nacos-settings');
  await expect(settings).toContainText('当前账号仅可查看连接设置');
  await expect(settings.getByLabel('Nacos 服务地址')).toBeDisabled();
  await expect(settings.getByRole('button',{name:'保存 Nacos 设置'})).toHaveCount(0);
  await expect(settings.getByLabel('Nacos 密码')).toHaveValue('');expect(remoteRequests).toBe(0);
});

test('Nacos settings keep tab drafts, preserve blank passwords, and fit narrow screens',async({page})=>{
  let stored={...nacosProfile},posted;
  await page.route('**/api/admin/nacos',route=>respond(route,{profile:stored,configured:true,can_edit:true,editor_username:'admin'}));
  await page.route('**/api/admin/nacos/save',route=>{posted=route.request().postDataJSON();const {password,...safe}=posted;stored={...safe,revision:2,password_set:true};return respond(route,{profile:stored,ready:true});});
  await login(page);await page.getByRole('button',{name:'Nacos 连接',exact:true}).click();const settings=page.locator('.nacos-settings');
  await settings.getByLabel('Nacos 服务地址').fill('http://new-nacos.internal:8848/nacos');
  await page.getByRole('button',{name:/业务数据库 ·/}).click();await page.getByRole('button',{name:'Nacos 连接',exact:true}).click();
  await expect(settings.getByLabel('Nacos 服务地址')).toHaveValue('http://new-nacos.internal:8848/nacos');
  await settings.getByText('TLS 与读取设置',{exact:true}).click();
  for(const width of [1440,390,320]){await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({animations:'disabled',path:`/tmp/wfs-nacos-${width}-${await page.locator('.nacos-settings:visible').count()?'settings':'platform'}.png`,fullPage:true});}
  await settings.getByRole('button',{name:'保存 Nacos 设置'}).click();await page.locator('.confirm-modal').getByRole('button',{name:'保存设置',exact:true}).click();
  await expect(settings.getByRole('status')).toContainText('已加密保存');
  expect(posted.password).toBe('');expect(posted.url).toBe('http://new-nacos.internal:8848/nacos');
  await expect(settings.getByLabel('Nacos 密码')).toHaveValue('');
  await page.screenshot({path:'/tmp/wfs-nacos-settings-mobile.png',fullPage:true});
});

test('platform Nacos save makes remote publication and restart boundary explicit',async({page})=>{
  let stored={...platformProfile},posted;
  await page.route('**/api/admin/platform-database',route=>respond(route,{can_edit:true,editor_username:'admin',active:platformProfile,saved:stored,restart_required:stored.revision>0,drivers:['DWS'],diagnostics:{processes:[],metrics:{}}}));
  await page.route('**/api/admin/platform-database/save',route=>{posted=route.request().postDataJSON();const {password,...safe}=posted;stored={...safe,revision:1,password_set:true};return respond(route,{profile:stored,ready:true,nacos_synced:true,restart_required:true});});
  await preview(page);await login(page);await page.getByRole('button',{name:'平台数据库',exact:true}).click();const pane=page.locator('.platform-database');
  await pane.getByRole('combobox',{name:'配置来源',exact:true}).selectOption('nacos');await pane.getByLabel('配置 Data ID').fill('scheduler-db.json');
  await expect(pane.getByRole('button',{name:'测试并保存待重启配置'})).toBeDisabled();
  await pane.getByRole('button',{name:'读取 Nacos 配置',exact:true}).click();
  await expect(pane.getByLabel('平台数据库地址')).toHaveValue('loaded-db.internal');
  await pane.getByText('字段映射与密码编码',{exact:true}).click();
  for(const width of [1440,390,320]){await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({animations:'disabled',path:`/tmp/wfs-nacos-${width}-${await page.locator('.nacos-settings:visible').count()?'settings':'platform'}.png`,fullPage:true});}
  await pane.getByRole('button',{name:'测试并保存待重启配置'}).click();
  await expect(page.locator('.confirm-modal')).toContainText('其他消费者也会读到修改');
  await page.locator('.confirm-modal').getByRole('button',{name:'测试并保存',exact:true}).click();
  await expect(pane.getByRole('status')).toContainText('已同步至 Nacos');await expect(pane).toContainText('当前版本 0');await expect(pane).toContainText('已有版本 1 的待生效配置');expect(posted.nacos_md5).toBe('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');expect(posted.nacos_settings_token).toBe('nacos-settings-version-a');
});

test('Nacos without authentication requires a read-only probe and reports precise verification',async({page})=>{
  let posted;await page.route('**/api/admin/nacos',route=>respond(route,{profile:nacosProfile,configured:true,can_edit:true,editor_username:'admin'}));
  await page.route('**/api/admin/nacos/test',route=>{posted=route.request().postDataJSON();return respond(route,{ready:true,verified:posted.probe_binding?'config_read':'authentication'});});
  await login(page);await page.getByRole('button',{name:'Nacos 连接',exact:true}).click();const pane=page.locator('.nacos-settings');
  await pane.getByRole('button',{name:'测试 Nacos 连接'}).click();await expect(pane.getByRole('status')).toContainText('尚未验证具体配置的读取及发布权限');
  await pane.getByLabel('启用 Nacos 账号认证').uncheck();await pane.getByRole('button',{name:'测试 Nacos 连接'}).click();await expect(pane.getByRole('alert')).toContainText('请填写');
  await pane.getByLabel('探测 Data ID').fill('read-probe.json');await pane.getByLabel('探测命名空间 ID').fill('namespace-uuid');
  await pane.getByRole('button',{name:'测试 Nacos 连接'}).click();await expect(pane.getByRole('status')).toContainText('配置读取验证通过');expect(posted.auth_enabled).toBe(false);expect(posted.probe_binding).toEqual({namespace:'namespace-uuid',group:'DEFAULT_GROUP',data_id:'read-probe.json'});
});

test('a Nacos revision conflict keeps the edited database draft for review',async({page})=>{
  await inventory(page,[databaseProfile]);await preview(page);
  await page.route('**/api/admin/database-connections/save',route=>route.fulfill({status:409,json:{status:'error',code:50000,message:'Nacos 配置已被修改，请重新读取后再保存。'}}));
  await login(page);const pane=page.locator('.connection-body');await pane.getByRole('button',{name:'编辑 reports'}).click();
  await pane.getByRole('button',{name:'读取 Nacos 配置',exact:true}).click();await pane.getByLabel('数据库地址',{exact:true}).fill('draft-db.internal');
  await pane.getByRole('button',{name:'测试并保存',exact:true}).click();await page.locator('.confirm-modal').getByRole('button',{name:'测试并同步保存'}).click();
  await expect(pane.getByRole('alert')).toContainText('Nacos 配置已被修改');await expect(pane.getByLabel('数据库地址',{exact:true})).toHaveValue('draft-db.internal');await expect(pane.getByRole('button',{name:'重新读取 Nacos 配置'})).toBeEnabled();
});
