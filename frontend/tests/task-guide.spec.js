import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('publishing guide provides executable examples, downloads and mobile layout', async ({
  page,
}) => {
  await page.goto('/#packages');
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码').fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  const guide = page.locator('.task-guide');
  await expect(guide).toBeVisible();
  await expect(guide).not.toHaveAttribute('open', '');
  await guide.locator('summary').click();
  const code = guide.getByLabel('示例代码', { exact: true });
  await expect(code).toContainText("if __name__ == '__main__':");
  const downloadPromise = page.waitForEvent('download');
  await guide
    .getByRole('button', { name: '下载 main.py', exact: true })
    .click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('main.py');
  expect(await readFile(await download.path(), 'utf8')).toBe(
    await code.textContent(),
  );
  await guide.getByRole('button', { name: '数据库查询', exact: true }).click();
  await expect(code).toContainText("with NewDB('mysql_orders')");
  await expect(guide).toContainText('任务不能使用保留标识 platform');
  await guide
    .getByRole('button', { name: '事务与批量写入', exact: true })
    .click();
  await expect(code).toContainText('with db.transaction():');
  await expect(guide).toContainText('ClickHouse 不支持此事务示例');
  await guide
    .getByRole('button', { name: '生成报表文件', exact: true })
    .click();
  await expect(code).toContainText('WFS_TASK_DATA_DIR');
  await guide
    .getByRole('button', { name: '离线依赖准备', exact: true })
    .click();
  await expect(code).toContainText('pip freeze > requirements.txt');
  await expect(guide).toContainText('全部间接依赖也必须锁定');
  await guide.getByRole('button', { name: '复制代码', exact: true }).click();
  await expect(guide.getByRole('status')).toContainText(
    /代码已复制|浏览器未允许复制/,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
