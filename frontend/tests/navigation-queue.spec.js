import {test,expect} from '@playwright/test';
async function login(page,route='tasks'){
 await page.goto('/#'+route);await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
}
test('task rows occupy the first desktop screen and mobile cards retain status',async({page})=>{
 await page.setViewportSize({width:1440,height:900});await login(page);
 const row=page.locator('.task-table tbody tr').first();await expect(row).toBeVisible();expect((await row.boundingBox()).y).toBeLessThan(750);
 await expect(page.locator('.batch-toolbar')).toHaveCount(0);await expect(page.getByLabel('维护原因')).not.toBeVisible();
 await page.getByRole('button',{name:'更多筛选',exact:true}).click();await expect(page.getByLabel('任务 ID',{exact:true})).toBeVisible();await page.getByRole('button',{name:'更多筛选',exact:true}).click();
 await page.screenshot({path:'test-results/task-desktop-review.png'});
 await page.setViewportSize({width:390,height:844});await expect(row.locator('.mobile-task-status')).toBeVisible();await expect(row.locator('.mobile-task-status')).toContainText('下次');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'test-results/task-mobile-review.png',fullPage:true});
});
test('system management sections preserve edits and support direct links',async({page})=>{
 await login(page,'admin');await expect(page.getByRole('button',{name:'系统管理',exact:true})).toBeVisible();
 const settings=page.locator('.dispatch-settings');await settings.locator('summary').click();await settings.getByLabel('全局并发名额').fill('3');
 await page.getByRole('button',{name:'账户权限',exact:true}).click();await expect(page.getByRole('heading',{name:'账户管理',exact:true})).toBeVisible();await expect(settings).not.toBeVisible();
 await page.getByRole('button',{name:'运行策略',exact:true}).click();await expect(settings.getByLabel('全局并发名额')).toHaveValue('3');
 await page.getByRole('button',{name:'任务列表',exact:true}).click();await expect(page.locator('.confirm-modal')).toContainText('未保存');await page.locator('.confirm-modal').getByRole('button',{name:'放弃修改并离开'}).click();
 await page.goto('/admin/#admin?section=storage');await expect(page.getByRole('button',{name:'存储备份',exact:true})).toHaveAttribute('aria-pressed','true');await expect(page.locator('.version-storage')).toBeVisible();await expect(page.getByRole('heading',{name:'账户管理',exact:true})).not.toBeVisible();
});
test('queue filters and cancels only after confirmation',async({page})=>{
 const id='queue_request_demo';let cancelled=false,params;
 await page.route('**/api/admin/operational/dispatch*',route=>{params=new URL(route.request().url()).searchParams;return route.fulfill({json:{code:20000,status:'success',data:{active:0,max_active:4,counts:{pending:cancelled?0:1},oldest_wait_seconds:123,total:1,page:1,page_size:25,items:[{id,pid:'acceptance__slow',task_name:'排队验收任务',kind:'scheduled',status:cancelled?'cancelled':'pending',wait_seconds:123,expires_at:'2026-10-30 12:00:00',message:'等待分组名额',run_id:''}]}}});});
 await page.route('**/api/admin/operational/requests',async route=>{expect(route.request().postDataJSON()).toEqual({action:'cancel',id});cancelled=true;await route.fulfill({json:{code:20000,status:'success',data:{}}});});
 await login(page,'queue');await expect(page.getByRole('heading',{name:'执行队列',exact:true})).toBeVisible();await page.getByLabel('任务名称或 ID').fill('验收');await page.getByLabel('请求状态',{exact:true}).selectOption('pending');await page.getByRole('button',{name:'查询',exact:true}).click();await expect.poll(()=>params.get('query')).toBe('验收');expect(params.get('status')).toBe('pending');
 await page.getByRole('button',{name:'取消请求',exact:true}).click();await expect(page.locator('.confirm-modal')).toContainText('不停用调度');expect(cancelled).toBe(false);await page.locator('.confirm-modal').getByRole('button',{name:'取消此请求'}).click();await expect(page.locator('.queue-table')).toContainText('已取消');await page.getByRole('button',{name:'排队策略',exact:true}).click();await expect(page.getByRole('heading',{name:'系统管理',exact:true})).toBeVisible();
});
