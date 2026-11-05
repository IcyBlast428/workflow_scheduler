import {test,expect} from '@playwright/test';
async function login(page,hash='matrix',name='admin'){
 await page.goto('/#'+hash);await page.getByLabel('用户名',{exact:true}).fill(name);await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
}
const ok=data=>({code:20000,data});
function recentFixture(stage=0,limit=10){return {server_time:'2026-11-04 12:00:00',limit,tasks:Array.from({length:24},(_,i)=>({pid:'task-'+i,name:'任务_'+String(i+1).padStart(2,'0'),group:['数据同步','报表任务','运维巡检','通知任务'][Math.floor(i/6)],records:Array.from({length:i===23?3:limit},(_,j)=>({key:i+'-'+j+'-'+stage,run_id:String(i*50+j).padStart(32,'0'),pid:'task-'+i,status:(i+j+stage)%4===0?'failed':'success',time:'2026-11-04 12:00:00',start_time:'2026-11-04 11:59:59',end_time:'2026-11-04 12:00:00',query_start:'2026-11-04 12:00:00',query_end:'2026-11-04 12:00:00',scope:'all'}))}))};}

test('recent results group columns horizontally, preserve selection and buffer hover updates',async({page})=>{
 await page.setViewportSize({width:1100,height:900});await page.clock.install();let stage=0;
 await page.route(/\/api\/taskinfo\/matrix-recent(?:\?|$)/,route=>route.fulfill({json:ok(recentFixture(stage))}));
 await page.route('**/api/taskinfo/run?**',route=>route.fulfill({json:ok({record:{status:'failed',task_name:'任务_01',start_time:'2026-11-04 11:59:59',end_time:'2026-11-04 12:00:00',code_version:{task_release:'abcdef0123456789'}},content:'ERROR 执行详情测试',start_offset:0,next_offset:0,log_size:0,log_unavailable:false,has_more:false})}));
 await login(page);const chart=page.locator('.recent-executions'),scroll=chart.locator('.recent-scroll');
 await expect(chart.locator('.recent-group')).toHaveCount(4);await expect(chart.locator('.recent-cell')).toHaveCount(240);await expect(chart.locator('.recent-cell:disabled')).toHaveCount(7);
 await expect(page.getByRole('navigation',{name:'工作区导航'}).getByRole('button',{name:'执行队列',exact:true})).toHaveCount(0);
 expect(await scroll.evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(true);
 await chart.locator('.recent-cell').first().click();await expect(chart.locator('.recent-selection')).toContainText('任务_01');
 const dialog=page.locator('.execution-modal');await expect(dialog.locator('.execution-output')).toContainText('执行详情测试');
 await expect(dialog.getByLabel('执行摘要')).toContainText('1.0 秒');await expect(dialog.getByLabel('执行摘要')).toContainText('abcdef012345');
 await expect(dialog.locator('.execution-reason')).toContainText('ERROR 执行详情测试');await expect(dialog.getByLabel('搜索当前日志片段')).toBeVisible();
 await dialog.locator('.modal-head button').click();await expect(dialog).not.toBeVisible();
 await scroll.evaluate(el=>el.scrollLeft=el.scrollWidth);const position=await scroll.evaluate(el=>el.scrollLeft);expect(position).toBeGreaterThan(0);
 await chart.getByRole('button',{name:'查看任务历史',exact:true}).click();await expect(page.getByLabel('任务编号',{exact:true})).toHaveValue('task-0');await expect(page).toHaveURL(/#matrix\?.*tab=logs/);
 await page.getByRole('button',{name:'最近结果',exact:true}).click();await expect(chart.locator('.recent-selection')).toContainText('任务_01');await expect.poll(()=>scroll.evaluate(el=>el.scrollLeft)).toBe(position);
 await page.getByRole('button',{name:'执行记录',exact:true}).click();
 await page.getByRole('button',{name:'清除任务编号',exact:true}).click();
 await expect(page.getByLabel('任务编号',{exact:true})).toHaveValue('');await expect(page.getByLabel('查询范围',{exact:true})).toHaveValue('all');
 await page.getByRole('button',{name:'最近结果',exact:true}).click();
 await scroll.evaluate(el=>el.scrollLeft=0);await chart.locator('.recent-cell').first().focus();
 stage=1;await page.clock.fastForward(5001);await expect(chart.getByRole('button',{name:'有新的执行结果 · 更新图表'})).toBeVisible();await expect(chart.locator('.recent-cell').first()).toHaveClass(/failed/);
 await chart.getByRole('button',{name:'有新的执行结果 · 更新图表'}).click();await expect(chart.locator('.recent-cell').first()).toHaveClass(/success/);await expect(chart.locator('.recent-selection')).toContainText('任务_01');
 await page.screenshot({path:'test-results/recent-result-matrix-desktop.png',fullPage:true});
 await scroll.evaluate(el=>el.scrollLeft=el.scrollWidth);expect(await scroll.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'test-results/recent-result-matrix-mobile.png',fullPage:true});
});

test('recent result depth supports only 10 and 25 and ignores an older response',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 let release25;
 await page.route(/\/api\/taskinfo\/matrix-recent(?:\?|$)/,async route=>{
  const limit=Number(new URL(route.request().url()).searchParams.get('limit'));
  if(limit===25 && !release25)await new Promise(resolve=>release25=resolve);
  await route.fulfill({json:ok(recentFixture(0,limit))});
 });
 await login(page);
 const chart=page.locator('.recent-executions'),depth=chart.getByLabel('执行次数'),scroll=chart.locator('.recent-scroll');
 await expect(depth.locator('option')).toHaveText(['10 次','25 次']);
 await expect(chart.locator('.recent-cell')).toHaveCount(240);
 await depth.selectOption('25');await expect.poll(()=>Boolean(release25)).toBe(true);
 await depth.selectOption('10');
 await expect(chart.getByRole('heading',{name:'最近 10 次执行结果'})).toBeVisible();
 await expect(chart.locator('.recent-cell')).toHaveCount(240);
 const olderResponse=page.waitForResponse(response=>new URL(response.url()).searchParams.get('limit')==='25');
 release25();await olderResponse;
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await expect(chart.getByRole('heading',{name:'最近 10 次执行结果'})).toBeVisible();
 await depth.selectOption('25');await expect(chart.locator('.recent-cell')).toHaveCount(600);
 expect(await scroll.evaluate(el=>el.scrollHeight>el.clientHeight && el.scrollWidth>el.clientWidth)).toBe(true);
 await page.getByRole('button',{name:'执行记录',exact:true}).click();await page.getByRole('button',{name:'最近结果',exact:true}).click();
 await expect(depth).toHaveValue('25');await expect(chart.locator('.recent-cell')).toHaveCount(600);
});

test('queue lives in the matrix and silently refreshes an empty state without disabling controls',async({page})=>{
 await page.clock.install();let requests=0,release;
 await page.route('**/api/admin/operational/dispatch**',async route=>{requests++;if(requests===2)await new Promise(resolve=>release=resolve);await route.fulfill({json:ok({items:[],page:1,total:0,max_active:4,counts:{},active:0})});});
 await login(page,'matrix?tab=queue');const queue=page.locator('.execution-queue'),button=queue.getByRole('button',{name:'刷新队列',exact:true});await expect(queue.locator('.empty-state')).toBeVisible();
 const before=await queue.boundingBox();await page.clock.fastForward(5001);await expect.poll(()=>requests).toBe(2);await expect(button).toBeEnabled();await expect(queue.locator('.empty-state')).toBeVisible();expect((await queue.boundingBox()).height).toBe(before.height);await expect(queue).not.toContainText('刷新中');
 release();await queue.getByLabel('请求状态').selectOption('pending');await queue.getByRole('button',{name:'查询',exact:true}).click();
 await expect(queue.locator('.empty-state')).toContainText('没有匹配的请求');
 await page.getByRole('button',{name:'执行记录',exact:true}).click();
 const hiddenRequests=requests;await page.clock.fastForward(5001);expect(requests).toBe(hiddenRequests);
 await page.getByRole('button',{name:'执行队列',exact:true}).click();await expect(queue.getByLabel('请求状态')).toHaveValue('pending');
});

test('completed results are buffered on log pages and explicit update returns to page one',async({page})=>{
 await page.clock.install();let revision=0,queries=[];const faults=[];page.on('pageerror',error=>faults.push(error.message));
 const row=name=>({logid:name,id:'task-log',name,datetime:'2026-11-04 12:00:00',starttime:'2026-11-04 11:59:00',state:'成功'});
 await page.route('**/api/taskinfo/events',route=>route.fulfill({json:ok({tasks:[],logs:{revision}})}));
 await page.route('**/api/taskinfo/taskLogs?**',route=>{const params=new URL(route.request().url()).searchParams;queries.push(params);const second=params.get('currentPage')==='2';return route.fulfill({json:ok({data:second?[row('第二页记录')]:revision?[row('新记录'+revision),row('原有记录')]:[row('原有记录')],total:30,has_more:!second,next_cursor:second?'':'next-cursor'})});});
 await login(page,'taskLogs');const original=page.getByRole('row').filter({hasText:'原有记录'});await expect(original).toBeVisible();await expect(page.getByRole('button',{name:'下一页',exact:true})).toBeEnabled();await expect(page.getByRole('button',{name:'搜索',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'? 搜索',exact:true})).toHaveCount(0);
  const y=(await original.boundingBox()).y;revision=1;await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));const update=page.getByRole('button',{name:'有新执行记录 · 点击查看'});await expect.poll(async()=>{await page.clock.fastForward(5001);return update.isVisible();}).toBe(true);await expect(page.getByRole('row').filter({hasText:'新记录1'})).toHaveCount(0);expect((await original.boundingBox()).y).toBe(y);
 await update.click();await expect(page.getByRole('row').filter({hasText:'新记录1'})).toBeVisible();await page.getByRole('button',{name:'下一页',exact:true}).click();
 const secondPageRow=page.getByRole('row').filter({hasText:'第二页记录'});await expect(secondPageRow).toBeVisible();
 await page.getByRole('button',{name:'最近结果',exact:true}).click();await page.getByRole('button',{name:'执行记录',exact:true}).click();
 await expect(secondPageRow).toBeVisible();expect(queries.at(-1).get('currentPage')).toBe('2');
 revision=2;await expect.poll(async()=>{await page.clock.fastForward(5001);return update.isVisible();}).toBe(true);await expect(secondPageRow).toBeVisible();await update.click();await expect(page.getByRole('row').filter({hasText:'新记录2'})).toBeVisible();expect(queries.at(-1).get('currentPage')).toBe('1');expect(faults).toEqual([]);
});

test('viewer can read recent results and cannot access matrix queue controls',async({page})=>{
 await login(page,'matrix?tab=queue','browser-viewer');await expect(page.locator('.recent-executions')).toBeVisible();const tabs=page.getByRole('navigation',{name:'任务执行分栏'});await expect(tabs.getByRole('button',{name:'执行队列',exact:true})).toHaveCount(0);await tabs.getByRole('button',{name:'执行记录',exact:true}).click();await expect(page.getByLabel('查询范围',{exact:true})).toBeVisible();expect((await page.request.get('/api/taskinfo/matrix-recent')).status()).toBe(200);expect((await page.request.get('/api/admin/operational/dispatch')).status()).toBe(403);
 expect((await page.request.get('/api/taskinfo/matrix-recent?limit=50')).status()).toBe(400);
 for(const limit of [10,25]){const response=await page.request.get(`/api/taskinfo/matrix-recent?limit=${limit}`);expect(response.status()).toBe(200);expect((await response.json()).data.limit).toBe(limit);}
});

test('horizontal three-dimensional timeline remains available in the unified workspace',async({page})=>{
 await page.setViewportSize({width:1600,height:1000});
 const tasks=recentFixture().tasks.slice(0,12).map(task=>({...task,configured:true,enabled:true}));
 const records=tasks.flatMap((task,i)=>[3,6,9,11].map(hour=>({key:task.pid+'-'+hour,pid:task.pid,run_id:'',status:(i+hour)%4===0?'failed':'success',time:`2026-11-04 ${String(hour).padStart(2,'0')}:00:00`,start_time:`2026-11-04 ${String(hour).padStart(2,'0')}:00:00`,end_time:`2026-11-04 ${String(hour).padStart(2,'0')}:00:00`,count:1})));
 await page.route(/\/api\/taskinfo\/matrix(?:\?|$)/,route=>route.fulfill({json:ok({tasks,records,active:[],pending:[],date:'2026-11-04',server_time:'2026-11-04 12:00:00',total_executions:records.length,aggregated:false,warnings:[],cursor:'horizontal-sample'})}));
 await login(page,'matrix?tab=timeline');await expect(page.locator('.matrix-surface')).toBeVisible();await expect(page.locator('.matrix-surface-note')).toContainText('时间由左向右');
 await expect(page.getByRole('button',{name:/全屏/})).toHaveCount(0);
 const toolbar=await page.locator('.matrix-toolbar').boundingBox(),summary=await page.locator('.matrix-summary').boundingBox();
 expect(summary.y-toolbar.y-toolbar.height).toBeLessThanOrEqual(20);
 const canvas=page.locator('.matrix-surface canvas'),box=await canvas.boundingBox();expect(box.width).toBeGreaterThan(box.height);
 await page.screenshot({path:'test-results/horizontal-execution-matrix.png',fullPage:true});
 await canvas.scrollIntoViewIfNeeded();
 const {x,y,width,height}=await canvas.boundingBox();
 const center={x:x+width/2,y:y+height/2};
 const savedZoom=()=>page.evaluate(()=>Object.entries(localStorage).find(([key])=>key.startsWith('wfs:matrix:'))?.[1]).then(value=>JSON.parse(value || '{}').camera?.zoom);
 await page.mouse.move(center.x,center.y);await page.keyboard.down('Alt');
 await page.mouse.down({button:'right'});await page.mouse.move(center.x+60,center.y,{steps:5});await page.mouse.up({button:'right'});
 await expect.poll(savedZoom).toBeGreaterThan(1);
 await page.mouse.down({button:'right'});await page.mouse.move(center.x-60,center.y,{steps:5});await page.mouse.up({button:'right'});
 await page.keyboard.up('Alt');await expect.poll(savedZoom).toBeLessThan(1);
 await page.getByRole('button',{name:'恢复全景',exact:true}).press('Alt+ArrowRight');await page.getByRole('button',{name:'恢复全景',exact:true}).click();await expect(canvas).toBeVisible();
});

test('GitLab background checks retain controls and existing content while pending',async({page})=>{
 await page.clock.install();let calls=0,release;
 await page.route('**/api/admin/gitlab-updates/state?**',async route=>{if(new URL(route.request().url()).searchParams.get('brief')==='true')return route.continue();calls++;if(calls>1)await new Promise(resolve=>release=resolve);await route.fulfill({json:ok({items:[],pending_merge:0,pending_release:0,count:0,checked_at:'2026-11-04 12:00:00',warnings:[]})});});
 await login(page,'gitlab');const button=page.getByRole('button',{name:'刷新列表',exact:true}),intro=page.locator('.gitlab-intro');await expect(button).toBeEnabled();await expect.poll(()=>calls).toBe(1);const before=await intro.boundingBox();await page.clock.fastForward(5001);await expect.poll(()=>calls).toBe(2);await expect(button).toBeEnabled();expect((await intro.boundingBox()).height).toBe(before.height);release();
});
