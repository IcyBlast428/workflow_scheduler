import {test,expect} from '@playwright/test';
import {navigate} from './navigation-helpers.js';
async function login(page,hash='dashboard'){
 await page.goto('/#'+hash);await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
}
test('six primary destinations, grouped settings, keyboard menu and narrow screen',async({page})=>{
 await login(page);
 await expect(page.getByRole('navigation',{name:'工作区导航'}).getByRole('button')).toHaveText(['总览','任务列表','执行矩阵','执行记录','代码更新']);
 await page.getByRole('button',{name:/账户菜单$/}).click();await expect(page.getByRole('menuitem',{name:'平台设置',exact:true})).toBeFocused();
 await page.keyboard.press('ArrowDown');await expect(page.getByRole('menuitem',{name:'平台事件',exact:true})).toBeFocused();await page.keyboard.press('Escape');await expect(page.getByRole('menu')).toHaveCount(0);
 await navigate(page,'数据库连接');await expect(page.locator('.connection-panel')).toBeVisible();
 await page.getByRole('button',{name:'审计与存储',exact:true}).click();await page.getByRole('button',{name:'存储清理与备份',exact:true}).click();
 await expect(page.locator('.log-storage')).toBeVisible();await page.locator('.log-storage').getByRole('button',{name:'预览日志清理'}).click();await expect(page.locator('.log-storage')).toContainText('本次检查未发现可清理日志');
 await page.screenshot({path:'test-results/navigation-storage-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'菜单',exact:true}).click();await page.getByRole('button',{name:/账户菜单$/}).click();await expect(page.getByRole('menuitem',{name:'平台设置'})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'test-results/navigation-storage-mobile.png',fullPage:true});
});
test('cleanup requires exact confirmation and submits the preview token',async({page})=>{
 let cleaned=false;
 await page.route('**/api/admin/operational/log-storage**',async route=>{
  if(route.request().method()==='POST'){expect(route.request().postDataJSON()).toEqual({token:'signed-preview',confirm:'清理 3 条执行日志'});cleaned=true;await route.fulfill({json:{code:20000,data:{count:3,bytes:1048576,skipped:0}}});}
  else await route.fulfill({json:{code:20000,data:{count:3,bytes:1048576,missing:0,inspected:3,skipped:0,days:90,cutoff:'2026-01-01 00:00:00',partial:false,confirm:'清理 3 条执行日志',token:'signed-preview',automatic_retention_days:90}}});
 });
 await login(page,'admin?section=storage');const panel=page.locator('.log-storage');await panel.getByRole('button',{name:'预览日志清理'}).click();const action=panel.getByRole('button',{name:'清理本批执行日志'});await expect(action).toBeDisabled();await panel.getByLabel('日志清理确认文字').fill('清理 3 条执行日志');await action.click();await expect(panel).toContainText('已清理 3 条');expect(cleaned).toBe(true);
});
test('large logs open at tail and paginate without loading the whole file',async({page})=>{
 const id='c'.repeat(32),seen=[];
 await page.route('**/api/taskinfo/run?**',async route=>{const offset=new URL(route.request().url()).searchParams.get('offset');seen.push(offset);const tail=offset==='tail';await route.fulfill({json:{code:20000,data:{record:{status:'success',task_name:'大日志测试'},content:tail?'TAIL_ONLY':'HEAD_ONLY',start_offset:tail?600000000-65536:0,next_offset:tail?600000000:65536,log_size:600000000,log_unavailable:false,has_more:!tail}}});});
 await login(page,'taskLogs?run='+id);const panel=page.locator('.execution-modal');await expect(panel.locator('.execution-output')).toContainText('TAIL_ONLY');expect(seen[0]).toBe('tail');await panel.getByRole('button',{name:'日志开头',exact:true}).click();await expect(panel.locator('.execution-output')).toContainText('HEAD_ONLY');await expect(panel.locator('.execution-output')).not.toContainText('TAIL_ONLY');await panel.getByRole('button',{name:'最新日志',exact:true}).click();await expect(panel.locator('.execution-output')).toContainText('TAIL_ONLY');
});
