import {test,expect} from '@playwright/test';
const runId='a'.repeat(32);
const ok=data=>({code:20000,data});
async function openMatrix(page){
 await page.route('**/api/taskinfo/matrix-recent*',route=>route.fulfill({json:ok({limit:25,tasks:[{
  pid:'prefetch-task',name:'详情复用测试',group:'测试组',records:[{key:'latest',pid:'prefetch-task',run_id:runId,status:'success',end_time:'2026-11-15 12:00:00',time:'2026-11-15 12:00:00'}]
 }]})}));
 await page.goto('/#matrix');
 await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('browser-test-password');
 await page.getByRole('button',{name:'登录',exact:true}).click();
 const latest=page.locator('.recent-task').first().locator('.recent-cell').last();await expect(latest).toBeEnabled();return latest;
}
function logResult(content,{status='success',start=100,next=120,size=120,more=false}={}){
 return {record:{status,task_name:'详情复用测试',pid:'prefetch-task'},content,start_offset:start,next_offset:next,log_size:size,log_unavailable:false,has_more:more};
}
test('matrix detail reuses one tail request, preserves paging and fetches fresh data on reopen',async({page})=>{
 await page.clock.install();const requests=[];
 await page.route('**/api/taskinfo/run?**',route=>{
  const offset=new URL(route.request().url()).searchParams.get('offset');requests.push(offset);
  return route.fulfill({json:ok(logResult(offset==='0'?'HEAD_ONLY':`TAIL_${requests.length}`,offset==='0'?{start:0,next:20,more:true}:{}))});
 });
 const latest=await openMatrix(page);await latest.click();
 const dialog=page.locator('.execution-modal');await expect(dialog.locator('.execution-output')).toHaveText('TAIL_1');
 await page.clock.fastForward(2000);expect(requests).toEqual(['tail']);
 await dialog.getByRole('button',{name:'日志开头',exact:true}).click();await expect(dialog.locator('.execution-output')).toHaveText('HEAD_ONLY');expect(requests).toEqual(['tail','0']);
 await dialog.locator('.modal-head button').click();await expect(dialog).not.toBeVisible();
 await latest.click();await expect(dialog.locator('.execution-output')).toHaveText('TAIL_3');expect(requests).toEqual(['tail','0','tail']);
});
test('prefetched running logs continue at the next offset without repeating the initial read',async({page})=>{
 await page.clock.install();const requests=[];
 await page.route('**/api/taskinfo/run?**',route=>{
  const offset=new URL(route.request().url()).searchParams.get('offset');requests.push(offset);
  return route.fulfill({json:ok(requests.length===1?logResult('INITIAL\n',{status:'running'}):logResult('APPENDED',{start:120,next:128,size:128}))});
 });
 const latest=await openMatrix(page);await latest.click();const output=page.locator('.execution-output');
 await expect(output).toHaveText('INITIAL\n');expect(requests).toEqual(['tail']);
 await page.clock.fastForward(1501);await expect(output).toHaveText('INITIAL\nAPPENDED');expect(requests).toEqual(['tail','120']);
 await page.clock.fastForward(5000);expect(requests).toEqual(['tail','120']);
});
for(const status of [400,404])test(`legacy history still falls back to its stored log after HTTP ${status}`,async({page})=>{
 const requests=[];
 await page.route('**/api/taskinfo/run?**',route=>{requests.push(new URL(route.request().url()).searchParams.get('offset'));return route.fulfill({status,json:{code:40000,message:'No retained run metadata'}});});
 await page.route('**/api/taskinfo/taskLogDetail**',route=>route.fulfill({json:ok('ARCHIVED_LOG')}));
 const latest=await openMatrix(page);await latest.click();
 await expect(page.getByRole('dialog',{name:'任务日志：prefetch-task'}).locator('.log-pre')).toContainText('ARCHIVED_LOG');
 await expect(page.locator('.execution-modal')).toHaveCount(0);expect(requests).toEqual(['tail']);
});
for (const status of [200, 400, 404]) test(`closing an initial read ignores a late HTTP ${status} response`,async({page})=>{
 let release, legacyReads=0;
 await page.route('**/api/taskinfo/run?**',async route=>{await new Promise(resolve=>release=resolve);await route.fulfill({status,json:status===200?ok(logResult('LATE_RESULT')):{code:40000,message:'No retained run metadata'}});});
 await page.route('**/api/taskinfo/taskLogDetail**',route=>{legacyReads++;return route.fulfill({json:ok('UNNECESSARY_READ')});});
 const latest=await openMatrix(page);await latest.click();
 const loading=page.getByRole('dialog',{name:'任务日志：prefetch-task'});await expect(loading).toContainText('正在加载日志');
 await expect.poll(()=>Boolean(release)).toBe(true);await loading.getByTitle('关闭', {exact:true}).click();
 const response=page.waitForResponse('**/api/taskinfo/run?**');release();await (await response).finished();
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 await expect(loading).not.toBeVisible();await expect(page.locator('.execution-modal')).toHaveCount(0);await expect(latest).toBeEnabled();
 expect(legacyReads).toBe(0, 'A closed dialog must not start a fallback history read');
});
