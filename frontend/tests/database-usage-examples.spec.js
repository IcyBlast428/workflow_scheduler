import {test,expect} from '@playwright/test';
import {navigate} from './navigation-helpers.js';

test('task documentation owns business examples and preserves type switching and HTTP copy',async({page})=>{
  await page.addInitScript(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined});document.execCommand=command=>{if(command==='copy'){window.exampleCopiedText=document.querySelector('textarea[readonly]')?.value;return true;}return false;};});
  const managementReads=[];
  page.on('request',request=>{if(/\/api\/admin\/(database-connections|platform-database|nacos)(?:\?|$)/.test(request.url()))managementReads.push(request.url());});
  await page.goto('/#packages');
  await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('browser-test-password');
  await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.locator('.task-examples')).toBeVisible();
  const examples=page.locator('.task-examples .database-usage-examples');
  await expect(examples.getByRole('heading',{name:'任务中的统一用法'})).toBeVisible();
  await expect(examples.locator('.connection-example')).toContainText('SELECT id, status FROM demo_db_usage');
  await examples.getByLabel('示例连接标识').fill('my_reports');
  await examples.getByLabel('示例类型',{exact:true}).selectOption('insert');await expect(examples.locator('pre')).toContainText('INSERT INTO');
  await examples.getByLabel('示例类型',{exact:true}).selectOption('async');await expect(examples.locator('pre')).toContainText('await db.async_execute');
  await examples.getByRole('button',{name:'复制示例'}).click();await expect(examples.getByRole('button',{name:'已复制'})).toBeVisible();
  expect(await page.evaluate(()=>window.exampleCopiedText)).toContain('NewDB("my_reports")');
  await examples.getByLabel('示例类型',{exact:true}).selectOption('transaction');
  await examples.getByLabel('示例数据库类型').selectOption('clickhouse');
  await expect(examples.getByLabel('示例类型',{exact:true}).locator('option[value="transaction"]')).toHaveCount(0);
  await examples.getByLabel('示例类型',{exact:true}).selectOption('delete');await expect(examples.locator('pre')).toContainText('ALTER TABLE');
  await examples.getByLabel('示例数据库类型').selectOption('postgresql');
  await examples.getByLabel('示例类型',{exact:true}).selectOption('async');
  expect(managementReads).toEqual([]);
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:900});
    await examples.scrollIntoViewIfNeeded();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    if(width!==320)await examples.screenshot({path:`/tmp/wfs-task-database-examples-${width}.png`});
  }
  await page.setViewportSize({width:1440,height:900});
  await navigate(page,'数据库连接');
  await expect(page.locator('.connection-body .database-usage-examples')).toHaveCount(0);
  await page.getByRole('button',{name:'平台数据库',exact:true}).click();
  const platform=page.locator('.platform-database .database-usage-examples');
  await expect(platform).toContainText('仅用于平台内部开发');await expect(platform).toContainText('任务示例与文档');
  await platform.getByLabel('示例类型',{exact:true}).selectOption('async');await expect(platform.locator('pre')).toContainText('await asyncio.to_thread');
});
