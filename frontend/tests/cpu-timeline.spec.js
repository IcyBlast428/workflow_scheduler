import {test,expect} from '@playwright/test';

test('CPU timeline keeps zoom, pan, tooltips and responsive sizing after extraction',async({page})=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 const now=new Date('2030-01-01T04:00:00Z');
 await page.clock.install({time:now});await page.clock.pauseAt(now);
 await page.setViewportSize({width:1440,height:1100});
 const samples=Array.from({length:73},(_,index)=>({time:new Date(now.getTime()-(72-index)*300000).toISOString(),cpu:20+index%30,memory:45+index%10}));
 await page.route(/\/api\/taskinfo\/dashboard(?:\?|$)/,route=>route.fulfill({json:{code:20000,data:{summary:{total:1,enabled:1},failure_rank:[],recent_runs:[],cpu_timeline:{current:32,current_memory:47,retention_hours:6,samples,markers:[{id:'chart-task',name:'测试任务',start_time:'2030-01-01 11:00:00',end_time:'2030-01-01 11:15:00',state:0,source:'history'}]}}}}));
 await page.goto('/#dashboard');await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();
 const chart=page.locator('.cpu-timeline'),line=chart.locator('.cpu-line');
 await expect(line).toBeVisible();await expect(chart.locator('.memory-line')).toBeVisible();
 const original=await line.getAttribute('d');
 await chart.scrollIntoViewIfNeeded();const before=await chart.boundingBox();
 await page.mouse.move(before.x+before.width*.9,before.y+100);await page.mouse.wheel(0,-400);
 await expect.poll(()=>line.getAttribute('d')).not.toBe(original);
 await expect(chart.locator('.cpu-grid text').last()).toHaveText('12:00');
 const zoomed=await line.getAttribute('d');
 await page.mouse.move(before.x+before.width*.6,before.y+100);await page.mouse.down({button:'middle'});await page.mouse.move(before.x+before.width*.6+90,before.y+100,{steps:5});await page.mouse.up({button:'middle'});
 await expect.poll(()=>line.getAttribute('d')).not.toBe(zoomed);
 await expect(chart).not.toHaveClass(/dragging/);
 await chart.locator('.task-block').first().hover();await expect(chart.locator('.cpu-tooltip')).toContainText('测试任务');
 await page.getByRole('button',{name:'展开图表',exact:true}).click();await expect.poll(async()=>Number((await chart.locator('svg.cpu-svg').getAttribute('viewBox')).split(' ')[3])).toBeGreaterThan(320);
 await page.setViewportSize({width:600,height:900});await expect.poll(async()=>Number((await chart.locator('svg.cpu-svg').getAttribute('viewBox')).split(' ')[2])).toBeLessThan(650);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(errors).toEqual([]);
});
