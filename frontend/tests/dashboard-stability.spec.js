import {test,expect} from '@playwright/test';
async function login(page){
 await page.goto('/#dashboard');await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
}

test('background attention checks preserve compact layout while the request is pending',async({page})=>{
 const now=new Date();await page.clock.install({time:now});await page.clock.pauseAt(now);
 let checks=0,release;
 const state={code:20000,data:{scheduler:{healthy:true},database:'GaussDB',issues:[]}};
 await page.route('**/api/taskinfo/attention',async route=>{checks++;if(checks>1)await new Promise(resolve=>release=resolve);await route.fulfill({json:state});});
 const dashboardResponse=page.waitForResponse(response=>response.url().includes('/api/taskinfo/dashboard'));
 await login(page);await (await dashboardResponse).finished();
 await expect(page.locator('.dashboard-loading')).toHaveCount(0);
 const card=page.locator('.attention-panel');await expect(card).toHaveClass(/is-clear/);
 const before=await card.boundingBox(),chartBefore=await page.locator('.cpu-panel').boundingBox();
 await page.clock.fastForward(30001);await expect.poll(()=>checks).toBe(2);await expect(card.getByRole('button',{name:'刷新',exact:true})).toBeDisabled();
 await expect(card).toHaveClass(/is-clear/);await expect(card).not.toContainText('正在检查运行状态');
 expect((await card.boundingBox()).height).toBe(before.height);expect((await page.locator('.cpu-panel').boundingBox()).y).toBe(chartBefore.y);
 release();await expect(card.getByRole('button',{name:'刷新',exact:true})).toBeEnabled();expect((await card.boundingBox()).height).toBe(before.height);
});

test('health indicators live above Admin without normal labels or an effects switch',async({page})=>{
 await page.setViewportSize({width:1440,height:900});
 await page.addInitScript(()=>localStorage.setItem('wfs:low-effects','true'));
 await login(page);
 const status=page.locator('.sidebar-account').getByRole('status',{name:'服务状态'});
 await expect(status.locator('[data-status="ready"]')).toHaveCount(3);await expect(status).not.toContainText('正常');
 await expect(page.getByRole('banner').getByRole('status',{name:'服务状态'})).toHaveCount(0);
 await expect(page.getByRole('button',{name:/简化特效|恢复特效/})).toHaveCount(0);
 expect(await page.evaluate(()=>localStorage.getItem('wfs:low-effects'))).toBeNull();
 const statusBounds=await status.boundingBox(),accountBounds=await page.getByRole('button',{name:/账户菜单$/}).boundingBox();expect(statusBounds.y+statusBounds.height).toBeLessThanOrEqual(accountBounds.y);
 expect((await status.getByLabel('接口：正常',{exact:true}).boundingBox()).y).toBe((await status.getByLabel('调度器：正常',{exact:true}).boundingBox()).y);
 await page.screenshot({path:'test-results/dashboard-health-desktop.png',fullPage:true});
 await page.getByRole('button',{name:'收起导航',exact:true}).click();await expect(status).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.setViewportSize({width:390,height:844});await expect(status).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'test-results/dashboard-health-mobile.png',fullPage:true});
});

test('overview counters wait for data and open tasks using their own filters', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const waitForDashboard = async route => {
    await gate;
    await route.continue();
  };
  await page.route('**/api/taskinfo/dashboard*', waitForDashboard);
  await page.route('**/api/taskinfo/attention', waitForDashboard);
  await login(page);
  const cards = page.locator('.dashboard-summary .metric-card');
  try {
    await expect(cards.locator('strong')).toHaveText(['—', '—', '—', '—']);
    await expect(cards.first()).toBeDisabled();
    await expect(page.getByRole('heading', { name: '最近执行记录' })).toHaveCount(0);
    await expect(page.locator('.attention-panel h2')).toHaveText('正在检查运行状态');
  } finally {
    release();
  }
  await expect(cards.first().locator('strong')).toHaveText(/^[1-9]/);
  await expect(page.getByRole('heading', { name: '最近执行记录' })).toHaveCount(0);

  const nav = page.getByRole('navigation', { name: '工作区导航' });
  await nav.getByRole('button', { name: '任务列表', exact: true }).click();
  await expect(page.locator('.task-name-link').first()).toBeVisible();
  await page.locator('#taskname').fill('ui-review-no-match');
  await page.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(page.getByText('没有匹配的任务', { exact: true })).toBeVisible();
  await nav.getByRole('button', { name: '总览', exact: true }).click();
  const total = await cards.first().locator('strong').innerText();
  await cards.first().click();
  await expect(page.locator('#taskname')).toHaveValue('');
  await expect(page.locator('.task-summary-strip').getByText('匹配任务')).toContainText(total);
  await expect(page.locator('.task-name-link').first()).toBeVisible();
  await page.reload();
  await expect(page.locator('#taskname')).toHaveValue('');
  await expect(page.locator('.task-name-link').first()).toBeVisible();

  await nav.getByRole('button', { name: '任务列表', exact: true }).click();
  await expect(page.locator('#taskname')).toHaveValue('ui-review-no-match');
  await expect(page.getByText('没有匹配的任务', { exact: true })).toBeVisible();
});
