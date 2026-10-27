import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';


test('nested project publication produces isolated CSV, JSON and escaped log downloads', async ({
  page,
}) => {
  test.setTimeout(100000);
  await page.goto('/#packages');
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码').fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  const exampleDownload = page.waitForEvent('download');
  await page.getByRole('link', { name: '下载多层目录示例 ZIP' }).click();
  expect((await exampleDownload).suggestedFilename()).toBe(
    'nested-task-example.zip',
  );
  await page.getByRole('button', { name: '任务列表', exact: true }).click();
  const row = page
    .locator('.task-table tbody tr')
    .filter({ hasText: '目录与输出验收' });
  await row.getByRole('button', { name: '手动执行', exact: true }).click();
  const dialog = page.locator('.execution-modal');
  await expect(dialog.locator('.execution-output')).toContainText(
    'ARTIFACT_RUN_OK',
  );
  await expect(dialog.locator('.execution-meta')).toContainText('成功');
  await dialog.getByRole('button', { name: '输出文件', exact: true }).click();
  const outputs = dialog.locator('.task-artifacts');
  await outputs
    .getByRole('button', { name: '打开目录 reports', exact: true })
    .click();
  await outputs
    .getByRole('button', { name: '预览文件 result.csv', exact: true })
    .click();
  await expect(outputs.locator('.artifact-csv')).toContainText('a,b');
  await expect(outputs.locator('.artifact-csv')).toContainText('42');
  const oldUrl = await outputs
    .getByRole('link', { name: '下载文件 result.csv', exact: true })
    .getAttribute('href');
  const csvDownload = page.waitForEvent('download');
  await outputs
    .getByRole('link', { name: '下载文件 result.csv', exact: true })
    .click();
  const downloaded = await csvDownload;
  expect(await readFile(await downloaded.path(), 'utf8')).toContain('"a,b",42');
  await outputs
    .getByRole('button', { name: '预览文件 summary.json', exact: true })
    .click();
  await expect(outputs.locator('.artifact-preview')).toContainText('run_id');
  await outputs
    .getByRole('button', { name: '预览文件 report.log', exact: true })
    .click();
  await expect(outputs.locator('.artifact-preview')).toContainText('<script>');
  expect(await page.evaluate(() => window.outputXss)).toBeUndefined();
  await dialog.getByTitle('关闭').click();
  await row.getByRole('button', { name: '手动执行', exact: true }).click();
  await expect(dialog.locator('.execution-meta')).toContainText('成功');
  await dialog.getByRole('button', { name: '输出文件', exact: true }).click();
  await outputs
    .getByRole('button', { name: '打开目录 reports', exact: true })
    .click();
  const newUrl = await outputs
    .getByRole('link', { name: '下载文件 result.csv', exact: true })
    .getAttribute('href');
  expect(newUrl).not.toBe(oldUrl);
  expect((await page.request.get(oldUrl)).status()).toBe(200);
  await dialog.getByTitle('关闭').click();
  await page.getByRole('button', { name: '执行记录', exact: true }).click();
  await page.getByLabel('任务名称', { exact: true }).fill('目录与输出验收');
  await page.getByRole('button', { name: '? 搜索', exact: true }).click();
  await page
    .getByRole('row')
    .filter({ hasText: '目录与输出验收' })
    .getByRole('button', { name: '详情', exact: true })
    .first()
    .click();
  await expect(dialog.locator('.execution-meta')).toContainText('成功');
  await dialog.getByRole('button', { name: '输出文件', exact: true }).click();
  await outputs
    .getByRole('button', { name: '打开目录 reports', exact: true })
    .click();
  await expect(
    outputs.getByRole('link', { name: '下载文件 result.csv', exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
});
