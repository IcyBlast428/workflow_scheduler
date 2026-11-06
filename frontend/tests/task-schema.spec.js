import {detailTab} from './navigation-helpers.js';
import {test,expect} from '@playwright/test';
test('DDL editing records history and tags filter the real task list',async({page})=>{
 await page.goto('/#tasks');await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('browser-test-password');await page.getByRole('button',{name:'登录',exact:true}).click();
 await page.locator('.task-table tbody tr').filter({hasText:'acceptance__slow'}).locator('.task-name-link').click();
 await detailTab(page,'DDL 与标签');const pane=page.getByLabel('DDL 与标签',{exact:true});
 await pane.getByLabel('标签（每行一个）').fill('核心链路\n日报');await pane.getByRole('button',{name:'保存标签',exact:true}).click();await expect(pane).toContainText('标签已保存');
 await pane.getByLabel('DDL 内容',{exact:true}).fill('CREATE TABLE report_day(id INTEGER);');await pane.getByLabel('修改说明',{exact:true}).fill('新增日报表定义');await pane.getByRole('button',{name:'保存 DDL 草稿',exact:true}).click();await expect(pane).toContainText('DDL 草稿已保存并记录历史');await expect(pane).toContainText('v1 · 新增日报表定义');
 await detailTab(page,'说明与配置');await detailTab(page,'DDL 与标签');await expect(pane.getByLabel('DDL 内容',{exact:true})).toHaveValue('CREATE TABLE report_day(id INTEGER);');
 await pane.getByLabel('DDL 内容',{exact:true}).fill('unsaved');await detailTab(page,'说明与配置');await expect(page.locator('.confirm-modal')).toContainText('未保存');await page.locator('.confirm-modal').getByRole('button',{name:'继续编辑',exact:true}).click();await expect(pane.getByLabel('DDL 内容',{exact:true})).toHaveValue('unsaved');
 await pane.getByLabel('DDL 内容',{exact:true}).fill('CREATE TABLE report_day(id INTEGER);');await page.getByRole('button',{name:'关闭',exact:true}).click();await page.getByLabel('标签',{exact:true}).fill('日报');await page.getByRole('button',{name:'搜索',exact:true}).click();await expect(page.locator('.task-table tbody tr')).toHaveCount(1);await expect(page.locator('.task-table')).toContainText('核心链路');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
