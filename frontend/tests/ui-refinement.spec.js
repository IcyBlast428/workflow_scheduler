import {test,expect} from '@playwright/test';
async function login(page,hash='tasks',username='admin'){
 await page.goto('/#'+hash);await page.getByLabel('用户名',{exact:true}).fill(username);await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
}
const slow=page=>page.locator('.task-table tbody tr').filter({hasText:'acceptance__slow'});
test('table preferences persist, optional columns remain accessible, batch lane stays put',async({page})=>{
 await page.setViewportSize({width:1440,height:1000});await login(page);
 await expect(page.locator('.task-table')).toHaveClass(/hide-group/);await expect(page.locator('.task-table thead th:visible')).toHaveCount(5);
 await page.getByLabel('任务列表密度').selectOption('compact');await page.getByText('显示列',{exact:true}).click();await page.locator('.column-options').getByLabel('活动实例 / 上限',{exact:true}).check();await page.getByText('显示列',{exact:true}).click();
 const before=await page.locator('.task-table').boundingBox();await slow(page).getByRole('checkbox').check();await expect(page.getByRole('button',{name:'批量暂停调度',exact:true})).toBeVisible();const after=await page.locator('.task-table').boundingBox();expect(Math.abs(before.y-after.y)).toBeLessThan(3);await page.getByRole('button',{name:'取消选择',exact:true}).click();
 await page.reload();await expect(page.locator('.task-table')).toHaveClass(/compact/);await expect(page.locator('.task-table')).not.toHaveClass(/hide-pending/);
 await page.screenshot({path:'test-results/ui-task-list.png',fullPage:true});
});
test('grouped workbench restores source URL, back navigation and unsaved edits',async({page,context})=>{
 await context.grantPermissions(['clipboard-read','clipboard-write']);await login(page);await slow(page).locator('.task-name-link').click();const dialog=page.locator('.task-workbench');
 await dialog.getByRole('navigation',{name:'任务工作区'}).getByRole('button',{name:'发布',exact:true}).click();await dialog.getByRole('tab',{name:'查看代码',exact:true}).click();await expect(page).toHaveURL(/detail=source/);await expect(dialog.getByRole('tab',{name:'查看代码',exact:true})).toHaveAttribute('aria-selected','true');
 await dialog.getByRole('button',{name:'复制当前链接',exact:true}).click();expect(await page.evaluate(()=>navigator.clipboard.readText())).toContain('detail=source');await page.reload();await expect(dialog.getByRole('tab',{name:'查看代码',exact:true})).toHaveAttribute('aria-selected','true');
 await dialog.getByRole('navigation',{name:'任务工作区'}).getByRole('button',{name:'概览',exact:true}).click();await expect(page).toHaveURL(/detail=description/);await page.goBack();await expect(dialog.getByRole('tab',{name:'查看代码',exact:true})).toHaveAttribute('aria-selected','true');
 await dialog.getByRole('tab',{name:'DDL 与标签',exact:true}).click();await dialog.getByLabel('DDL 内容',{exact:true}).fill('unsaved example');await dialog.getByRole('navigation',{name:'任务工作区'}).getByRole('button',{name:'概览',exact:true}).click();await expect(page.locator('.confirm-modal')).toContainText('未保存');await page.getByRole('button',{name:'继续编辑',exact:true}).click();await expect(dialog.getByLabel('DDL 内容',{exact:true})).toHaveValue('unsaved example');await page.screenshot({path:'test-results/ui-task-workbench.png',fullPage:true});
});
test('matrix only renders real rows and keeps labels sticky and columns aligned',async({page})=>{
 const records=Array.from({length:2},(_,i)=>({key:'r'+i,pid:'task-a',run_id:(''+i).repeat(32),status:i?'failed':'success',time:'2026-11-06 10:00:00'}));
 await page.route('**/api/taskinfo/matrix-recent*',route=>route.fulfill({json:{code:20000,data:{limit:10,tasks:[{pid:'task-a',name:'多层目录任务',group:'第一组',records},{pid:'task-b',name:'输出报告',group:'第一组',records:[]},{pid:'task-c',name:'不同组任务',group:'第二组',records}]}}}));await login(page,'matrix');
 await expect(page.locator('.recent-task')).toHaveCount(3);await expect(page.locator('.recent-task').first().locator('.recent-cell')).toHaveCount(2);await expect(page.locator('.recent-ranks>span')).toHaveText(['1','2']);
 const names=await page.locator('.recent-task-name').evaluateAll(nodes=>nodes.map(n=>({x:n.getBoundingClientRect().x,y:n.getBoundingClientRect().y,position:getComputedStyle(n).position})));expect(names[1].x-names[0].x).toBe(42);expect(names[2].x-names[1].x).toBeGreaterThan(42);expect(names.every(n=>n.position==='sticky')).toBe(true);
 await page.getByLabel('仅显示已有行').uncheck();await expect(page.locator('.recent-task').first().locator('.recent-cell')).toHaveCount(10);await page.screenshot({path:'test-results/ui-recent-matrix.png',fullPage:true});
});
test('schedule explains ownership and shows edited values before saving',async({page})=>{
 await login(page);await slow(page).getByRole('button',{name:'更多',exact:true}).click();await page.locator('.action-menu').getByRole('button',{name:'配置',exact:true}).click();const dialog=page.locator('.schedule-modal');await expect(dialog.locator('.configuration-guide')).toContainText('依赖环境');await expect(dialog.locator('#main-file')).not.toBeVisible();await dialog.locator('#task-name').fill('新的展示名称');await expect(dialog.getByLabel('保存前变更摘要')).toContainText('新的展示名称');await expect(dialog.getByLabel('保存前变更摘要')).toContainText('任务名称');await dialog.locator('.entry-override summary').click();await expect(dialog.locator('#main-file')).toBeVisible();await page.screenshot({path:'test-results/ui-schedule-review.png',fullPage:true});
});
test('healthy dashboard stays compact and chart expands on demand',async({page})=>{
 await page.route('**/api/taskinfo/attention',route=>route.fulfill({json:{code:20000,data:{scheduler:{healthy:true},database:'GaussDB',issues:[]}}}));await login(page,'dashboard');const card=page.locator('.attention-panel');await expect(card).toHaveClass(/is-clear/);await expect(card.locator('.panel-body')).not.toBeVisible();expect((await page.locator('.cpu-timeline').boundingBox()).height).toBe(320);await page.getByRole('button',{name:'展开图表',exact:true}).click();expect((await page.locator('.cpu-timeline').boundingBox()).height).toBeGreaterThanOrEqual(420);await card.getByRole('button',{name:'查看状态',exact:true}).click();await expect(card.locator('.panel-body')).toBeVisible();
});
test('viewer workbench on mobile exposes only permitted groups and no overflow',async({page})=>{
 await page.setViewportSize({width:390,height:844});await login(page,'tasks','browser-viewer');await slow(page).locator('.task-name-link').click();const dialog=page.locator('.task-workbench');await expect(dialog.getByRole('navigation',{name:'任务工作区'}).getByRole('button')).toHaveText(['概览','执行']);await dialog.getByRole('navigation',{name:'任务工作区'}).getByRole('button',{name:'执行',exact:true}).click();await expect(dialog.getByRole('tab',{name:'执行记录',exact:true})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);const bounds=await dialog.boundingBox();expect(bounds.y).toBeGreaterThanOrEqual(0);expect(bounds.y+bounds.height).toBeLessThanOrEqual(844);await page.screenshot({path:'test-results/ui-viewer-mobile.png'});
});
