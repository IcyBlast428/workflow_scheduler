import {navigate} from './navigation-helpers.js';
import {test,expect} from '@playwright/test';
async function login(page,view='dashboard'){
 await page.goto('/#'+view);await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
}
test('missing lazy module shows recovery and refreshing restores the same page',async({page})=>{
 await login(page);
 await page.route('**/static/ExecutionMatrixWorkspace-*.js',route=>route.fulfill({status:404,body:'Missing old chunk'}));
 await page.getByRole('button',{name:'执行矩阵',exact:true}).click();await expect(page.locator('.asset-recovery')).toBeVisible();
 await page.unroute('**/static/ExecutionMatrixWorkspace-*.js');await page.getByRole('button',{name:'刷新页面资源',exact:true}).click();
 await expect(page.locator('.recent-executions')).toBeVisible();await expect(page.locator('.asset-recovery')).toHaveCount(0);await expect(page).toHaveURL(/#matrix$/);
});
test('resource recovery asks before discarding an edited form',async({page})=>{
 await login(page,'admin');const settings=page.locator('.dispatch-settings');await settings.locator('summary').click();await expect(settings.getByLabel('全局并发名额')).toHaveValue('4');await settings.getByLabel('全局并发名额').fill('3');
 await page.evaluate(()=>window.dispatchEvent(new Event('vite:preloadError')));await page.getByRole('button',{name:'刷新页面资源',exact:true}).click();await expect(page.locator('.confirm-modal')).toContainText('未保存');await page.locator('.confirm-modal').getByRole('button',{name:'继续编辑',exact:true}).click();await expect(settings.getByLabel('全局并发名额')).toHaveValue('3');
});
test('all workspace navigation routes load fresh assets',async({page})=>{
 const errors=[];const missing=[];page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.url().includes('/static/')&&r.status()>=400)missing.push(r.url());});
 await login(page);
 for(const [label,selector] of [['任务列表','.task-table'],['执行队列','.execution-queue'],['执行矩阵','.matrix-summary'],['执行记录','.log-shortcuts'],['平台事件','#system-log-id'],['任务示例','.task-examples'],['依赖仓库','.repository-settings'],['系统管理','.admin-panel'],['代码更新','.gitlab-workspace'],['数据库连接','.connection-panel'],['总览','.cpu-panel']]){
  await navigate(page,label);await expect(page.locator(selector)).toBeVisible();
 }
 expect(errors).toEqual([]);expect(missing).toEqual([]);
});
