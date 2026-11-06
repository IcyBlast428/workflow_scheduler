import {test,expect} from '@playwright/test';
async function login(page,username='admin'){
  await page.goto('/#admin');await page.getByLabel('用户名',{exact:true}).fill(username);
  await page.getByLabel('密码',{exact:true}).fill('browser-test-password');
  await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
}
test('runtime diagnostics expose real aggregate metadata only to administrators',async({page})=>{
  await login(page);await expect(page.getByRole('heading',{name:'性能诊断',exact:true})).toBeVisible();
  const response=await page.request.get('/api/admin/runtime');expect(response.ok()).toBe(true);
  const {data}=await response.json();expect(data.performance.window_seconds).toBe(900);
  expect(data.performance.per_process_limit).toBe(512);expect(data.performance.sources.length).toBeGreaterThan(0);
  expect(data.metrics['database:connect'].samples).toBeGreaterThan(0);
  expect(data.execution_health.cache_seconds).toBe(30);
  await page.locator('.diagnostics summary').click();await expect(page.locator('.diagnostics')).toContainText('不能相加');
  await page.screenshot({path:'test-results/runtime-diagnostics.png',fullPage:true});
});
test('runtime refresh pauses outside its section, keeps stale data and recovers after failures',async({page})=>{
  await page.clock.install();let calls=0,fail=false;
  const body={code:20000,data:{performance:{window_seconds:900,per_process_limit:512,sources:[{pid:1,role:'web',age_seconds:0}],metrics:{'database:connect':{samples:10,p50_ms:4,p95_ms:12,max_ms:20}}},execution_health:{failure_rate:20,attempts:10,failures:2,counts:{cancelled:3},to:'2026-11-06 10:00:00'}}};
  await page.route('**/api/admin/runtime',route=>{calls++;return route.fulfill(fail?{status:503,json:{message:'temporary failure'}}:{json:body});});
  await login(page);await expect(page.locator('.diagnostics')).toContainText('12.0 ms');await expect(page.locator('.diagnostics')).toContainText('20%');
  await page.getByRole('button',{name:'账户与权限',exact:true}).click();const paused=calls;
  await page.clock.fastForward(65000);expect(calls).toBe(paused);
  fail=true;await page.getByRole('button',{name:'运行与发布',exact:true}).click();await expect(page.locator('.runtime-status')).toContainText('性能状态更新失败');
  await expect(page.locator('.diagnostics')).toContainText('12.0 ms');const failed=calls;
  await page.clock.fastForward(30001);expect(calls).toBe(failed);
  fail=false;await page.clock.fastForward(30001);await expect.poll(()=>calls).toBe(failed+1);
  await expect(page.locator('.runtime-status')).not.toContainText('性能状态更新失败');
});
test('viewer cannot read platform diagnostics',async({page})=>{
  await login(page,'browser-viewer');expect((await page.request.get('/api/admin/runtime')).status()).toBe(403);
  await expect(page.getByRole('heading',{name:'性能诊断',exact:true})).toHaveCount(0);
});
test('hidden and offline pages pause reads and resume with one fresh request',async({page})=>{
  const now=new Date();await page.clock.install({time:now});await page.clock.pauseAt(now);
  let calls=0;await page.route('**/api/admin/runtime',route=>{calls++;return route.fulfill({json:{code:20000,data:{}}});});
  await login(page);await expect(page.getByRole('heading',{name:'性能诊断',exact:true})).toBeVisible();
  await expect.poll(()=>calls).toBe(1);
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
  await page.clock.fastForward(120000);expect(calls).toBe(1);
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));});
  await expect.poll(()=>calls).toBe(2);
  await page.evaluate(()=>{Object.defineProperty(navigator,'onLine',{configurable:true,value:false});window.dispatchEvent(new Event('offline'));});
  await page.clock.fastForward(120000);expect(calls).toBe(2);
  await page.evaluate(()=>{Object.defineProperty(navigator,'onLine',{configurable:true,value:true});window.dispatchEvent(new Event('online'));});
  await expect.poll(()=>calls).toBe(3);
});
