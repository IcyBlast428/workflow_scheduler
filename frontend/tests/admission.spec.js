import { test, expect } from '@playwright/test';
async function login(page, route='tasks') {
  await page.goto('/#'+route);
  await page.getByLabel('用户名',{exact:true}).fill('admin');
  await page.getByLabel('密码',{exact:true}).fill('browser-test-password');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await expect(page.getByRole('button',{name:'任务列表',exact:true})).toBeVisible();
}
test('maintenance rejects new requests, preserves receipts and drains running tasks',async({page})=>{
  await login(page);
  const headers={'X-CSRF-Token':await page.evaluate(()=>sessionStorage.getItem('wfs_csrf_token'))};
  const key='browser_receipt_'+Date.now();
  const call=()=>page.request.post('/api/taskinfo/call_task?pid=acceptance__slow',{headers,data:{request_id:key}});
  const first=await call();expect(first.status()).toBe(200);const run=(await first.json()).data.run_id;
  await expect.poll(async()=>((await(await page.request.get('/api/taskinfo/run?run_id='+run)).json()).data.record.status)).toBe('running');
  const panel=page.getByLabel('执行维护模式');
  await panel.getByRole('button',{name:'进入维护',exact:true}).click();
  await page.locator('.confirm-modal').getByRole('button',{name:'进入维护',exact:true}).click();
  await expect(panel).toContainText('维护模式：暂停启动新执行');
  try {
    expect((await(await call()).json()).data.run_id).toBe(run);
    const blocked=await page.request.post('/api/taskinfo/call_task?pid=acceptance__slow',{headers,data:{request_id:key+'_new'}});
    expect(blocked.status()).toBe(409);
    await page.reload();await expect(panel).toContainText('维护模式：暂停启动新执行');
    await expect.poll(async()=>((await(await page.request.get('/api/taskinfo/run?run_id='+run)).json()).data.record.status),{timeout:20000}).toBe('success');
  } finally {
    const state=(await(await page.request.get('/api/admin/admission')).json()).data;
    await page.request.post('/api/admin/admission',{headers,data:{enabled:false,revision:state.revision,reason:''}});
  }
});
test('legacy platform source and embedded task authorization workspace',async({page})=>{
  const faults=[];page.on('pageerror',e=>faults.push(e.message));
  await login(page,'connections');
  await expect(page.getByText(/配置来源：本地 SQLite/)).toBeVisible();
  await expect(page.getByRole('button',{name:'测试并保存（重启生效）'})).toHaveCount(0);
  await page.getByRole('button',{name:'任务列表',exact:true}).click();
  const row=page.locator('.task-table tbody tr').filter({hasText:'acceptance__slow'});
  await row.getByRole('button',{name:'详情',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByRole('tab',{name:'连接授权',exact:true}).click();
  await expect(dialog.getByLabel('访问模式')).toHaveValue('legacy');
  await dialog.getByLabel('访问模式').selectOption('restricted');
  await dialog.getByRole('button',{name:'保存授权',exact:true}).click();
  await page.locator('.confirm-modal').getByRole('button',{name:'保存授权',exact:true}).click();
  await expect(dialog).toContainText('授权已保存，下次执行生效');
  await dialog.getByRole('tab',{name:'代码版本',exact:true}).click();
  await expect(page.getByRole('dialog')).toHaveCount(1);
  await expect(dialog.getByText('GitLab 代码审查与任务版本')).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(faults).toEqual([]);
});
