import {test, expect} from '@playwright/test';

const runId='e'.repeat(32);
const logText='{"business_date":"2026-11-15","amount":100}\n'+'long-log-'.repeat(120);
async function mockExecution(page) {
  await page.route('**/api/taskinfo/run?**',route=>route.fulfill({json:{code:20000,data:{
    record:{pid:'acceptance__slow',task_name:'执行布局检查',status:'success',source:'manual',actor:'admin',start_time:'2026-11-15 12:00:00',end_time:'2026-11-15 12:00:01'},
    content:logText,start_offset:0,next_offset:logText.length,log_size:logText.length,log_unavailable:false,has_more:false,
  }}}));
  await page.route('**/api/taskinfo/artifacts?**',route=>route.fulfill({json:{code:20000,data:{entries:[],directory:'',offset:0,has_more:false,truncated:false}}}));
}
async function login(page,hash) {
  await page.goto('/#'+hash);
  await page.getByLabel('用户名',{exact:true}).fill('admin');
  await page.getByLabel('密码',{exact:true}).fill('browser-test-password');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}
async function checkLogSpacing(dialog) {
  await expect(dialog.locator('.execution-output')).toHaveText(logText);
  const geometry=await dialog.locator('.execution-log-panel').evaluate(panel=>{
    const [navigation,search]=panel.querySelectorAll('.filter-actions');
    const output=panel.querySelector('pre');
    const n=navigation.getBoundingClientRect(),s=search.getBoundingClientRect(),o=output.getBoundingClientRect();
    return {firstGap:s.top-n.bottom,secondGap:o.top-s.bottom,overflow:panel.scrollWidth-panel.clientWidth};
  });
  expect(geometry.firstGap).toBeGreaterThanOrEqual(10);
  expect(geometry.secondGap).toBeGreaterThanOrEqual(10);
  expect(geometry.overflow).toBeLessThanOrEqual(1);
  const follow=dialog.locator('.execution-log-follow');
  const alignment=await follow.evaluate(label=>{
    const checkbox=label.querySelector('input').getBoundingClientRect();
    const range=document.createRange();range.selectNode(label.lastChild);const text=range.getBoundingClientRect();
    return {textHeight:text.height,centerDifference:Math.abs((checkbox.top+checkbox.bottom-text.top-text.bottom)/2)};
  });
  expect(alignment.textHeight).toBeLessThan(28);
  expect(alignment.centerDifference).toBeLessThan(4);
}
for(const embedded of [false,true]) test(`${embedded?'embedded':'standalone'} execution keeps tool gaps and wraps long logs at desktop and narrow widths`,async({page})=>{
  await page.setViewportSize({width:1440,height:1000});await mockExecution(page);
  await login(page,embedded?`tasks?pid=acceptance__slow&detail=runs&detailRun=${runId}`:`matrix?tab=logs&run=${runId}`);
  const dialog=page.locator(embedded?'.task-workbench .embedded-workspace':'.execution-modal');
  await expect(dialog).toBeVisible();
  if (!embedded) {
    await expect(dialog.locator('.execution-output')).toHaveText(logText);
    const unused=await dialog.evaluate(el=>{const body=el.querySelector('.execution-body'),output=el.querySelector('.execution-output');return body.getBoundingClientRect().bottom-output.getBoundingClientRect().bottom-parseFloat(getComputedStyle(body).paddingBottom);});
    expect(unused).toBeLessThan(3);
    expect(unused).toBeGreaterThanOrEqual(-1);
  }
  for(const size of [{width:1440,height:1000},{width:768,height:900},{width:390,height:844}]) {
    await page.setViewportSize(size);await checkLogSpacing(dialog);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
  await dialog.getByRole('button',{name:'输出文件',exact:true}).click();
  const outputs=dialog.getByLabel('本次执行输出文件');
  await expect(outputs).toContainText('此目录还没有输出文件');
  expect(await outputs.locator(':scope > .loading-status').evaluate(el=>el.getBoundingClientRect().height)).toBeLessThanOrEqual(4);
  expect(await outputs.locator(':scope > .filter-actions').count()).toBe(1);
  await dialog.getByRole('button',{name:'执行日志',exact:true}).click();
  await checkLogSpacing(dialog);
  await page.screenshot({path:`test-results/execution-layout-${embedded?'embedded':'standalone'}-mobile.png`});
});

for(const viewport of [{width:1440,height:1000},{width:390,height:844}]) test(`large multiline logs stay bounded and open at the tail at ${viewport.width}px`,async({page})=>{
  await page.setViewportSize(viewport);
  const content=Array.from({length:2000},(_,i)=>`Line ${i+1}: task output with diagnostic details`).join('\n');
  await page.route('**/api/taskinfo/run?**',route=>route.fulfill({json:{code:20000,data:{
    record:{pid:'acceptance__slow',task_name:'多行日志布局检查',status:'success'},content,
    start_offset:0,next_offset:content.length,log_size:content.length,log_unavailable:false,has_more:false,
  }}}));
  await login(page,`matrix?tab=logs&run=${runId}`);
  const output=page.locator('.execution-modal .execution-output');
  await expect(output).toContainText('Line 2000:');
  await expect.poll(()=>output.evaluate(el=>el.scrollHeight-el.clientHeight-el.scrollTop)).toBeLessThan(2);
  const size=await output.evaluate(el=>({height:el.clientHeight,content:el.scrollHeight,width:el.clientWidth,scrollWidth:el.scrollWidth}));
  expect(size.height).toBeGreaterThan(150);
  expect(size.height).toBeLessThan(viewport.height);
  expect(size.content).toBeGreaterThan(size.height*2);
  expect(size.scrollWidth).toBeLessThanOrEqual(size.width+1);
});
