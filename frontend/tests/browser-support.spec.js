import { test, expect } from '@playwright/test';

for (const [name, agent] of [
  ['IE 8', 'Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1)'],
  ['IE 11 / Edge IE mode', 'Mozilla/5.0 (Windows NT 10.0; Trident/7.0; rv:11.0) like Gecko'],
]) {
  test.describe(name, () => {
    test.use({ userAgent: agent, javaScriptEnabled: false });
    test('server blocks the app and displays the notice without JavaScript', async ({ page }, testInfo) => {
      const requests = [];
      page.on('request', request => requests.push(request.url()));
      const response = await page.goto('/admin/#tasks');
      expect(response.status()).toBe(403);
      await expect(page.getByRole('heading', { name: '当前浏览器不受支持' })).toBeVisible();
      await expect(page.getByRole('alert')).toContainText('请使用 Chrome 内核浏览器');
      await expect(page.getByRole('alert')).toContainText('请退出 IE 模式');
      await expect(page.locator('#app')).toHaveCount(0);
      expect(requests.some(url => url.includes('/api/') || /\.js(?:\?|$)/.test(url))).toBe(false);
      await page.screenshot({ path: testInfo.outputPath('browser-notice.png'), fullPage: true });
    });
  });
}

test('documentMode catches compatibility mode with a customized user agent', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(document, 'documentMode', { value: 7 }));
  const apiRequests = [];
  page.on('request', request => { if (request.url().includes('/api/')) apiRequests.push(request.url()); });
  await page.goto('/#tasks');
  await expect(page.getByRole('heading', { name: '当前浏览器不受支持' })).toBeVisible();
  await expect(page.locator('#app')).toBeHidden();
  expect(apiRequests).toEqual([]);
});

test('Chromium still reaches the login page', async ({ page }) => {
  const response = await page.goto('/admin/#tasks');
  expect(response.status()).toBe(200);
  await expect(page.getByLabel('用户名', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '当前浏览器不受支持' })).toBeHidden();
});
