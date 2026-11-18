import {test,expect} from '@playwright/test';
async function login(page,hash='tasks',username='admin'){
 await page.goto('/#'+hash);await page.getByLabel('用户名',{exact:true}).fill(username);await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
}
const slow=page=>page.locator('.task-table tbody tr').filter({hasText:'acceptance__slow'});
test('phone task list shows a full task before scrolling and reveals operational warnings', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let maintenance = false;
  await page.route('**/api/admin/admission', route => route.fulfill({
    json: { code: 20000, data: { enabled: maintenance, revision: 1, active: [], reserved: 0 } },
  }));
  let gitlabError = '';
  await page.route('**/api/taskinfo/packages/gitlab', route => route.fulfill({
    json: { code: 20000, data: { enabled: Boolean(gitlabError), items: [], error: gitlabError } },
  }));
  await login(page);
  const firstTask = page.locator('.task-table tbody tr').first();
  await expect(firstTask).toBeVisible();
  const firstTaskBounds = await firstTask.boundingBox();
  expect(firstTaskBounds.y + firstTaskBounds.height).toBeLessThan(844);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await expect(page.getByLabel('任务状态', { exact: true })).toBeVisible();
  await expect(page.getByText('匹配任务')).toBeVisible();
  await expect(page.getByLabel('标签', { exact: true })).toBeHidden();
  await page.getByRole('button', { name: '更多筛选', exact: true }).click();
  await expect(page.getByLabel('标签', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '更多筛选', exact: true }).click();
  const services = page.locator('.task-services');
  await expect(services.locator('summary')).toContainText('执行接收正常');
  await expect(page.getByLabel('执行维护模式')).toBeHidden();
  await services.locator('summary').click();
  await expect(page.getByLabel('执行维护模式')).toBeVisible();
  await services.locator('summary').click();
  await expect(page.getByLabel('执行维护模式')).toBeHidden();
  const settings = page.locator('.list-settings');
  await expect(page.getByRole('switch', { name: '任务列表密度 · 紧凑模式' })).toBeHidden();
  await settings.locator(':scope > summary').click();
  await expect(page.getByRole('switch', { name: '任务列表密度 · 紧凑模式' })).toBeVisible();
  await settings.getByText('显示列', { exact: true }).click();
  await expect(settings.getByLabel('组名', { exact: true })).toBeVisible();
  await settings.locator(':scope > summary').click();
  maintenance = true;
  gitlabError = '示例检查失败';
  await page.reload();
  await expect(page.getByText('维护模式：暂停启动新执行')).toBeVisible();
  const gitlab = page.getByRole('region', { name: 'GitLab 任务变更', exact: true });
  await expect(gitlab.getByText('检查异常')).toBeVisible();
  await gitlab.getByRole('button', { name: '查看连接与检查状态', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'GitLab 连接与检查状态', exact: true });
  await expect(dialog.getByRole('alert')).toHaveText(gitlabError);
});

test('account drafts are protected when leaving the page or replacing the account', async ({ page }) => {
  await login(page);
  const accountsHash = '#admin?section=accounts';
  await page.evaluate(hash => { location.hash = hash; }, accountsHash);
  const name = page.locator('#account-name');
  const confirmation = page.locator('.confirm-modal');
  const tasks = page.getByRole('button', { name: '任务列表', exact: true });
  await name.fill('unsaved-account');
  await tasks.click();
  await confirmation.getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(name).toHaveValue('unsaved-account');
  await page.goBack();
  await confirmation.getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(page).toHaveURL(/#admin\?section=accounts$/);
  await expect(name).toBeVisible();
  await expect(name).toHaveValue('unsaved-account');
  const edit = page.getByRole('row').filter({ hasText: 'browser-viewer' })
    .getByRole('button', { name: '编辑', exact: true });
  await edit.click();
  await confirmation.getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(name).toHaveValue('unsaved-account');
  await edit.click();
  await confirmation.getByRole('button', { name: '放弃修改', exact: true }).click();
  await expect(name).toHaveValue('browser-viewer');
  await name.fill('second-unsaved-account');
  await tasks.click();
  await confirmation.getByRole('button', { name: '放弃修改并离开', exact: true }).click();
  await expect(page).toHaveURL(/#tasks$/);
  await page.evaluate(hash => { location.hash = hash; }, accountsHash);
  await expect(name).toHaveValue('');
});

test('compact task list keeps text size, hides IDs and remembers columns on desktop and phone', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page);
  const table = page.locator('.task-table');
  const firstName = table.locator('.task-name-link').first();
  const density = page.getByRole('switch', { name: '任务列表密度 · 紧凑模式' });
  const columns = page.getByText('显示列', { exact: true });
  const activity = page.locator('.column-options').getByLabel('活动实例 / 上限', { exact: true });
  await expect(table.locator('.task-row-id').first()).toBeVisible();
  await expect(table.locator('thead th:visible')).toHaveCount(5);
  const nameSize = await firstName.evaluate(element => getComputedStyle(element).fontSize);

  await expect(density).toHaveText(/^\s*标准\s*紧凑\s*$/);
  await expect(density).toHaveAttribute('aria-checked', 'false');
  await density.press('Space');
  await expect(density).toHaveAttribute('aria-checked', 'true');
  await expect(firstName).toHaveCSS('font-size', nameSize);
  await expect(table.locator('.task-row-id')).toHaveCount(0);
  await columns.click();
  await activity.check();
  await columns.click();
  await expect(table.getByRole('columnheader', { name: '活动实例 / 上限' })).toBeVisible();
  const before = await table.boundingBox();
  await table.getByRole('checkbox', { name: '选择任务 acceptance__slow', exact: true }).check();
  await expect(page.getByRole('button', { name: '批量暂停调度', exact: true })).toBeVisible();
  const after = await table.boundingBox();
  expect(Math.abs(before.y - after.y)).toBeLessThan(3);
  await page.getByRole('button', { name: '取消选择', exact: true }).click();

  await page.reload();
  await expect(table).toHaveClass(/compact/);
  await expect(density).toHaveAttribute('aria-checked', 'true');
  await expect(table.getByRole('columnheader', { name: '活动实例 / 上限' })).toBeVisible();
  await columns.click();
  await expect(activity).toBeChecked();
  await columns.click();
  await page.screenshot({ path: 'test-results/ui-task-list.png', fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  const firstCard = table.locator('.mobile-task-status').first();
  await expect(firstCard).toContainText(/活动 \d+ \/ \d+/);
  await expect(firstName).toHaveCSS('font-size', nameSize);
  await expect(table.locator('.task-row-id')).toHaveCount(0);
  await page.locator('.list-settings > summary').click();
  await density.getByText('标准', { exact: true }).click();
  await expect(density).toHaveAttribute('aria-checked', 'false');
  await expect(table.locator('.task-row-id').first()).toBeVisible();
  await columns.click();
  await activity.uncheck();
  await expect(firstCard).not.toContainText('活动');
  await page.reload();
  await expect(firstCard).not.toContainText('活动');
  await page.locator('.list-settings > summary').click();
  await expect(density).toHaveAttribute('aria-checked', 'false');
});
test('grouped workbench restores source URL, back navigation and unsaved edits',async({page,context})=>{
 await context.grantPermissions(['clipboard-read','clipboard-write']);await login(page);await slow(page).locator('.task-name-link').click();const dialog=page.locator('.task-workbench');
 await dialog.getByRole('navigation',{name:'任务工作区'}).getByRole('button',{name:'发布',exact:true}).click();await dialog.getByRole('tab',{name:'查看代码',exact:true}).click();await expect(page).toHaveURL(/detail=source/);await expect(dialog.getByRole('tab',{name:'查看代码',exact:true})).toHaveAttribute('aria-selected','true');
 await dialog.getByRole('button',{name:'复制当前链接',exact:true}).click();expect(await page.evaluate(()=>navigator.clipboard.readText())).toContain('detail=source');await page.reload();await expect(dialog.getByRole('tab',{name:'查看代码',exact:true})).toHaveAttribute('aria-selected','true');
 await dialog.getByRole('navigation',{name:'任务工作区'}).getByRole('button',{name:'概览',exact:true}).click();await expect(page).toHaveURL(/detail=description/);await page.goBack();await expect(dialog.getByRole('tab',{name:'查看代码',exact:true})).toHaveAttribute('aria-selected','true');
 await dialog.getByRole('tab',{name:'DDL 与标签',exact:true}).click();await dialog.getByLabel('DDL 内容',{exact:true}).fill('unsaved example');await dialog.getByRole('navigation',{name:'任务工作区'}).getByRole('button',{name:'概览',exact:true}).click();await expect(page.locator('.confirm-modal')).toContainText('未保存');await page.getByRole('button',{name:'继续编辑',exact:true}).click();await expect(dialog.getByLabel('DDL 内容',{exact:true})).toHaveValue('unsaved example');await page.screenshot({path:'test-results/ui-task-workbench.png',fullPage:true});
});
test('recent matrix keeps 25 slots, newest results at the bottom and vertical names below them',async({page})=>{
 await page.setViewportSize({width:1440,height:1200});
 const records=Array.from({length:2},(_,i)=>({key:'r'+i,pid:'task-a',run_id:(''+i).repeat(32),status:i?'failed':'success',time:'2026-11-06 10:00:00'}));
 const longName='多层目录中的每日业务数据同步任务';
 await page.route('**/api/taskinfo/matrix-recent*',route=>route.fulfill({json:{code:20000,data:{limit:25,tasks:[{pid:'task-a',name:longName,group:'第一组',records},{pid:'task-b',name:'输出报告',group:'第一组',records:[]},{pid:'task-c',name:'不同组任务',group:'第二组',records}]}}}));await login(page,'matrix');
 const tasks=page.locator('.recent-task'),cells=tasks.first().locator('.recent-cell'),scroll=page.locator('.recent-scroll');
 await expect(tasks).toHaveCount(3);await expect(cells).toHaveCount(25);
 await expect(page.locator('.recent-ranks>span')).toHaveText(Array.from({length:25},(_,i)=>String(25-i)));
 await expect(tasks.first().locator('.recent-cell:disabled')).toHaveCount(23);
 await expect(cells.nth(22)).toBeDisabled();await expect(cells.nth(23)).toHaveClass(/failed/);await expect(cells.last()).toHaveClass(/success/);
 await expect(cells.last()).toHaveAttribute('aria-label',/最近第 1 次/);await expect(cells.nth(23)).toHaveAttribute('aria-label',/最近第 2 次/);
 await expect(tasks.nth(1).locator('.recent-cell:disabled')).toHaveCount(25);
 await expect(page.getByLabel('仅显示已有行')).toHaveCount(0);
 await expect(tasks.first().locator('.recent-task-name')).toHaveAttribute('title',longName+' · task-a');
 await expect.poll(()=>scroll.evaluate(el=>Math.abs(el.scrollHeight-el.clientHeight-el.scrollTop))).toBeLessThan(2);
 const names=await page.locator('.recent-task-name').evaluateAll(nodes=>nodes.map(n=>({x:n.getBoundingClientRect().x,y:n.getBoundingClientRect().y,position:getComputedStyle(n).position,writing:getComputedStyle(n.firstElementChild).writingMode,previous:n.previousElementSibling?.classList.contains('recent-cell')})));
 expect(names[1].x-names[0].x).toBe(42);expect(names[2].x-names[1].x).toBeGreaterThan(42);
 expect(names.every(n=>n.position==='sticky' && n.writing==='vertical-rl' && n.previous)).toBe(true);
 const glyphHeight=await tasks.first().locator('.recent-task-name span').evaluate(el=>{const range=document.createRange();range.setStart(el.firstChild,0);range.setEnd(el.firstChild,1);return range.getBoundingClientRect().height;});
 expect(glyphHeight).toBeGreaterThanOrEqual(10);
 const latest=await cells.last().boundingBox(),rank=await page.locator('.recent-ranks>span').last().boundingBox();
 expect(names[0].y).toBeGreaterThanOrEqual(latest.y+latest.height);expect(Math.abs(rank.y-latest.y)).toBeLessThan(1);
 await page.getByLabel('最近执行分类').selectOption('第二组');await expect(tasks).toHaveCount(1);await expect(tasks.locator('.recent-cell')).toHaveCount(25);
 await page.getByLabel('最近执行分类').selectOption('');
 await page.screenshot({path:'test-results/ui-recent-matrix.png',fullPage:true});
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
