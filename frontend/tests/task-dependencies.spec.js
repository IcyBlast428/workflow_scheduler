import {test, expect} from '@playwright/test';
import {detailTab} from './navigation-helpers.js';

test('same-code dependency recovery creates a candidate, preserves edits and installs on request', async ({page}) => {
  const faults=[];page.on('pageerror',error=>faults.push(error.message));
  await page.goto('/#tasks');
  await page.getByLabel('用户名',{exact:true}).fill('admin');
  await page.getByLabel('密码',{exact:true}).fill('browser-test-password');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.locator('.task-table tbody tr').filter({hasText:'acceptance__slow'}).locator('.task-name-link').click();
  await detailTab(page,'代码版本');
  const dialog=page.locator('.task-workbench');
  const original=await dialog.locator('.release-history .btn.primary').textContent();
  await dialog.getByRole('button',{name:'用原代码重新准备依赖',exact:true}).click();
  await expect(dialog.getByRole('button',{name:'识别并安装依赖',exact:true})).toBeEnabled();
  await expect(dialog.locator('.release-history .btn.primary')).not.toHaveText(original);
  await dialog.locator('summary').filter({hasText:'补充或调整依赖'}).click();
  const input=dialog.getByLabel('本版本完整依赖清单');
  await input.fill('requests\npandas');
  await dialog.getByRole('button',{name:'刷新发布检查',exact:true}).click();
  await expect(input).toHaveValue('requests\npandas');
  await page.setViewportSize({width:390,height:844});
  await input.scrollIntoViewIfNeeded();
  expect(await dialog.locator('.release-dependencies').evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true);
  await page.screenshot({path:'../data/task-dependencies-mobile.png'});
  // No external package registry in a browser test: inspect the exact request and
  // simulate a repository failure; backend tests perform real wheel installation.
  let submitted;
  await page.route('**/api/taskinfo/packages/action',async route=>{
    submitted=route.request().postDataJSON();
    await route.fulfill({status:400,json:{code:100,status:'failure',message:'Nexus 中未找到可用依赖：pandas。',data:{}}});
  });
  await dialog.getByRole('button',{name:'识别并安装依赖',exact:true}).click();
  await expect.poll(()=>submitted?.requirements).toBe('requests\npandas');
  await expect(dialog.locator('.release-body > .inline-alert.danger')).toContainText('Nexus');
  await expect(input).toHaveValue('requests\npandas');
  await input.fill('');
  await page.unroute('**/api/taskinfo/packages/action');
  await dialog.getByRole('button',{name:'识别并安装依赖',exact:true}).click();
  await expect(dialog.getByRole('button',{name:'发布此版本',exact:true})).toBeVisible({timeout:30000});
  await expect(dialog.locator('.release-check-summary .passed')).toContainText('依赖环境：检查通过');
  await expect(dialog.locator('.release-history')).toContainText(original);
  expect(faults).toEqual([]);
});
