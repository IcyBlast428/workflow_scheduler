import {test,expect} from '@playwright/test';
async function login(page,hash='matrix',name='admin'){
 await page.goto('/#'+hash);await page.getByLabel('用户名',{exact:true}).fill(name);await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
}
const ok=data=>({code:20000,data});
function recentFixture(stage=0){return {server_time:'2026-11-04 12:00:00',limit:10,tasks:Array.from({length:24},(_,i)=>({pid:'task-'+i,name:'任务_'+String(i+1).padStart(2,'0'),group:['数据同步','报表任务','运维巡检','通知任务'][Math.floor(i/6)],records:Array.from({length:i===23?3:10},(_,j)=>({key:i+'-'+j+'-'+stage,run_id:String(i*10+j).padStart(32,'0'),pid:'task-'+i,status:(i+j+stage)%4===0?'failed':'success',time:'2026-11-04 12:00:00',start_time:'2026-11-04 11:59:59',end_time:'2026-11-04 12:00:00',query_start:'2026-11-04 12:00:00',query_end:'2026-11-04 12:00:00',scope:'all'}))}))};}

test('recent results group columns horizontally, preserve selection and buffer hover updates',async({page})=>{
 await page.setViewportSize({width:1440,height:900});await page.clock.install();let stage=0;
 await page.route('**/api/taskinfo/matrix-recent',route=>route.fulfill({json:ok(recentFixture(stage))}));
 await login(page);const chart=page.locator('.recent-executions'),scroll=chart.locator('.recent-scroll');
 await expect(chart.locator('.recent-group')).toHaveCount(4);await expect(chart.locator('.recent-cell')).toHaveCount(240);await expect(chart.locator('.recent-cell:disabled')).toHaveCount(7);
 await expect(page.getByRole('navigation',{name:'工作区导航'}).getByRole('button',{name:'执行队列',exact:true})).toHaveCount(0);
 expect(await scroll.evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(true);
 await chart.locator('.recent-cell').first().click();await expect(chart.locator('.recent-selection')).toContainText('任务_01');
 stage=1;await page.clock.fastForward(5001);await expect(chart.getByRole('button',{name:'有新的执行结果 · 更新图表'})).toBeVisible();await expect(chart.locator('.recent-cell').first()).toHaveClass(/failed/);
 await chart.getByRole('button',{name:'有新的执行结果 · 更新图表'}).click();await expect(chart.locator('.recent-cell').first()).toHaveClass(/success/);await expect(chart.locator('.recent-selection')).toContainText('任务_01');
 await page.screenshot({path:'test-results/recent-result-matrix-desktop.png',fullPage:true});
 await scroll.evaluate(el=>el.scrollLeft=el.scrollWidth);expect(await scroll.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'test-results/recent-result-matrix-mobile.png',fullPage:true});
});

test('queue lives in the matrix and silently refreshes an empty state without disabling controls',async({page})=>{
 await page.clock.install();let requests=0,release;
 await page.route('**/api/admin/operational/dispatch**',async route=>{requests++;if(requests>1)await new Promise(resolve=>release=resolve);await route.fulfill({json:ok({items:[],page:1,total:0,max_active:4,counts:{},active:0})});});
 await login(page,'matrix?tab=queue');const queue=page.locator('.execution-queue'),button=queue.getByRole('button',{name:'刷新队列',exact:true});await expect(queue.locator('.empty-state')).toBeVisible();
 const before=await queue.boundingBox();await page.clock.fastForward(5001);await expect.poll(()=>requests).toBe(2);await expect(button).toBeEnabled();await expect(queue.locator('.empty-state')).toBeVisible();expect((await queue.boundingBox()).height).toBe(before.height);await expect(queue).not.toContainText('刷新中');
 release();await expect.poll(()=>release!=null).toBe(true);
});

test('completed results are buffered on log pages and explicit update returns to page one',async({page})=>{
 await page.clock.install();let revision=0,queries=[];const faults=[];page.on('pageerror',error=>faults.push(error.message));
 const row=name=>({logid:name,id:'task-log',name,datetime:'2026-11-04 12:00:00',starttime:'2026-11-04 11:59:00',state:'成功'});
 await page.route('**/api/taskinfo/events',route=>route.fulfill({json:ok({tasks:[],logs:{revision}})}));
 await page.route('**/api/taskinfo/taskLogs?**',route=>{const params=new URL(route.request().url()).searchParams;queries.push(params);const second=params.get('currentPage')==='2';return route.fulfill({json:ok({data:second?[row('第二页记录')]:revision?[row('新记录'+revision),row('原有记录')]:[row('原有记录')],total:30,has_more:!second,next_cursor:second?'':'next-cursor'})});});
 await login(page,'taskLogs');const original=page.getByRole('row').filter({hasText:'原有记录'});await expect(original).toBeVisible();await expect(page.getByRole('button',{name:'下一页',exact:true})).toBeEnabled();await expect(page.getByRole('button',{name:'搜索',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'? 搜索',exact:true})).toHaveCount(0);
  const y=(await original.boundingBox()).y;revision=1;await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));const update=page.getByRole('button',{name:'有新执行记录 · 点击查看'});await expect.poll(async()=>{await page.clock.fastForward(5001);return update.isVisible();}).toBe(true);await expect(page.getByRole('row').filter({hasText:'新记录1'})).toHaveCount(0);expect((await original.boundingBox()).y).toBe(y);
 await update.click();await expect(page.getByRole('row').filter({hasText:'新记录1'})).toBeVisible();await page.getByRole('button',{name:'下一页',exact:true}).click();await expect(page.getByRole('row').filter({hasText:'第二页记录'})).toBeVisible();revision=2;await expect.poll(async()=>{await page.clock.fastForward(5001);return update.isVisible();}).toBe(true);await expect(page.getByRole('row').filter({hasText:'第二页记录'})).toBeVisible();await update.click();await expect(page.getByRole('row').filter({hasText:'新记录2'})).toBeVisible();expect(queries.at(-1).get('currentPage')).toBe('1');expect(faults).toEqual([]);
});

test('viewer can read recent results and cannot access matrix queue controls',async({page})=>{
 await login(page,'matrix?tab=queue','browser-viewer');await expect(page.locator('.recent-executions')).toBeVisible();await expect(page.getByRole('navigation',{name:'执行矩阵分栏'}).getByRole('button',{name:'执行队列',exact:true})).toHaveCount(0);expect((await page.request.get('/api/taskinfo/matrix-recent')).status()).toBe(200);expect((await page.request.get('/api/admin/operational/dispatch')).status()).toBe(403);
});

test('horizontal three-dimensional timeline remains available in the unified workspace',async({page})=>{
 await page.setViewportSize({width:1600,height:1000});
 const tasks=recentFixture().tasks.slice(0,12).map(task=>({...task,configured:true,enabled:true}));
 const records=tasks.flatMap((task,i)=>[3,6,9,11].map(hour=>({key:task.pid+'-'+hour,pid:task.pid,run_id:'',status:(i+hour)%4===0?'failed':'success',time:`2026-11-04 ${String(hour).padStart(2,'0')}:00:00`,start_time:`2026-11-04 ${String(hour).padStart(2,'0')}:00:00`,end_time:`2026-11-04 ${String(hour).padStart(2,'0')}:00:00`,count:1})));
 await page.route(/\/api\/taskinfo\/matrix(?:\?|$)/,route=>route.fulfill({json:ok({tasks,records,active:[],pending:[],date:'2026-11-04',server_time:'2026-11-04 12:00:00',total_executions:records.length,aggregated:false,warnings:[],cursor:'horizontal-sample'})}));
 await login(page,'matrix?tab=timeline');await expect(page.locator('.matrix-surface')).toBeVisible();await expect(page.locator('.matrix-surface-note')).toContainText('时间由左向右');
 const canvas=page.locator('.matrix-surface canvas'),box=await canvas.boundingBox();expect(box.width).toBeGreaterThan(box.height);
 await page.screenshot({path:'test-results/horizontal-execution-matrix.png',fullPage:true});
 await page.getByRole('button',{name:'恢复全景',exact:true}).press('Alt+ArrowRight');await page.getByRole('button',{name:'恢复全景',exact:true}).click();await expect(canvas).toBeVisible();
});

test('GitLab background checks retain controls and existing content while pending',async({page})=>{
 await page.clock.install();let calls=0,release;
 await page.route('**/api/admin/gitlab-updates/state?**',async route=>{if(new URL(route.request().url()).searchParams.get('brief')==='true')return route.continue();calls++;if(calls>1)await new Promise(resolve=>release=resolve);await route.fulfill({json:ok({items:[],pending_merge:0,pending_release:0,count:0,checked_at:'2026-11-04 12:00:00',warnings:[]})});});
 await login(page,'gitlab');const button=page.getByRole('button',{name:'刷新列表',exact:true}),intro=page.locator('.gitlab-intro');await expect(button).toBeEnabled();await expect.poll(()=>calls).toBe(1);const before=await intro.boundingBox();await page.clock.fastForward(5001);await expect.poll(()=>calls).toBe(2);await expect(button).toBeEnabled();expect((await intro.boundingBox()).height).toBe(before.height);release();
});
