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
  await expect(guide).toHaveAttribute('open', '');
  const code = guide.getByLabel('示例代码', { exact: true });
  await expect(code).toContainText("if __name__ == '__main__':");
  await expect(code.locator('.hljs-keyword').first()).toBeVisible();
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
  await expect(code).toContainText('WFS_OUTPUT_DIR');
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

test('administrators maintain highlighted examples and Nexus settings across reloads', async ({
  page,
}) => {
  await page.goto('/#packages');
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码').fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  const guide = page.locator('.task-guide');
  await guide
    .getByRole('button', { name: '新增示例类型', exact: true })
    .click();
  await guide
    .getByLabel('示例类型名称', { exact: true })
    .fill('浏览器新增示例');
  await guide
    .getByLabel('示例源码', { exact: true })
    .fill('print("CUSTOM_EXAMPLE")\n# <img src=x onerror=alert(1)>');
  await guide.getByRole('button', { name: '保存示例', exact: true }).click();
  await expect(guide.getByRole('status')).toContainText('示例已保存');
  await expect(guide.getByLabel('示例代码', { exact: true })).toContainText(
    'CUSTOM_EXAMPLE',
  );
  await expect(
    guide.getByLabel('示例代码', { exact: true }).locator('img'),
  ).toHaveCount(0);
  await guide.getByRole('button', { name: '编辑此示例', exact: true }).click();
  await guide
    .getByLabel('示例源码', { exact: true })
    .fill('print("EDITED_EXAMPLE")');
  await guide.getByRole('button', { name: '保存示例', exact: true }).click();
  await expect(guide.getByLabel('示例代码', { exact: true })).toContainText(
    'EDITED_EXAMPLE',
  );
  const repository = page.locator('.repository-settings');
  await page.getByRole('button', { name:'依赖仓库', exact:true }).click();
  await repository
    .getByLabel('依赖安装方式', { exact: true })
    .selectOption('nexus');
  await repository
    .getByLabel('Nexus pip 索引地址', { exact: true })
    .fill('http://nexus.immp.icbc/repository/pypi-hosted');
  await repository
    .getByRole('button', { name: '保存仓库设置', exact: true })
    .click();
  await expect(repository.getByRole('status')).toContainText('仓库设置已保存');
  await page.reload();
  await page.getByRole('button', { name:'任务示例', exact:true }).click();
  await guide
    .getByRole('button', { name: '浏览器新增示例', exact: true })
    .click();
  await expect(guide.getByLabel('示例代码', { exact: true })).toContainText(
    'EDITED_EXAMPLE',
  );
  await page.getByRole('button', { name:'依赖仓库', exact:true }).click();
  await expect(
    repository.getByLabel('依赖安装方式', { exact: true }),
  ).toHaveValue('nexus');
  await expect(
    repository.getByLabel('Nexus pip 索引地址', { exact: true }),
  ).toHaveValue('http://nexus.immp.icbc/repository/pypi-hosted/simple/');
  await repository
    .getByLabel('依赖安装方式', { exact: true })
    .selectOption('offline');
  await repository
    .getByRole('button', { name: '保存仓库设置', exact: true })
    .click();
  await expect(repository.getByRole('status')).toContainText('仓库设置已保存');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
