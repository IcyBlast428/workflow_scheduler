import { test, expect } from '@playwright/test';

test('queue settings save, validate, reload and fit a narrow viewport', async ({page}) => {
  const faults=[];page.on('pageerror',e=>faults.push(e.message));
  await page.goto('/#admin');
  await page.getByLabel('用户名',{exact:true}).fill('admin');
  await page.getByLabel('密码',{exact:true}).fill('browser-test-password');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  const settings=page.locator('.dispatch-settings');
  await settings.locator('summary').click();
  await expect(settings.getByLabel('全局并发名额')).toHaveValue('4');
  await settings.getByLabel('全局并发名额').fill('2');
  await settings.getByRole('button',{name:'保存排队策略'}).click();
  await expect(settings.getByRole('status').filter({hasText:'排队策略已保存'})).toBeVisible();
  await page.reload();await settings.locator('summary').click();
  await expect(settings.getByLabel('全局并发名额')).toHaveValue('2');
  await settings.getByLabel('主机持续高负载时暂缓启动').check();
  await expect(settings.getByLabel('CPU 暂缓阈值（%）')).toHaveValue('85');
  await settings.getByLabel('主机持续高负载时暂缓启动').uncheck();
  await settings.getByLabel('全局并发名额').fill('4');
  await settings.getByRole('button',{name:'保存排队策略'}).click();
  await page.setViewportSize({width:390,height:844});
  await expect(settings.getByRole('button',{name:'保存排队策略'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(faults).toEqual([]);
});
