import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';

function zip(files) {
  return execFileSync(
    process.env.WFS_BROWSER_PYTHON || 'python3',
    [
      '-c',
      'import io,json,sys,zipfile; b=io.BytesIO(); z=zipfile.ZipFile(b,"w"); [z.writestr(k,v) for k,v in json.loads(sys.stdin.read()).items()]; z.close(); sys.stdout.buffer.write(b.getvalue())',
    ],
    { input: JSON.stringify(files) },
  );
}

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
  await page.locator('.package-panel > .panel-head')
    .getByRole('button', { name: '新增任务', exact: true }).click();
  await page.getByLabel('任务名称', { exact: true }).fill('目录与输出验收');
  await page.getByLabel('任务分类', { exact: true }).fill('outputs');
  await page.getByLabel('目录名称', { exact: true }).fill('nested');
  await page
    .getByLabel('ZIP 目录处理', { exact: true })
    .selectOption('preserve');
  const files = {
    'src/report_job/__init__.py': '',
    'src/report_job/helpers.py': 'value = 42\n',
    'src/report_job/main.py': `from .helpers import value
import csv, json, os
from pathlib import Path
root=Path(os.environ['WFS_TASK_ROOT'])
assert (root/'resources/input.txt').read_text() == 'INPUT_OK'
out=Path(os.environ['WFS_OUTPUT_DIR'])/'reports'
out.mkdir()
with (out/'result.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.writer(stream);writer.writerow(['name','amount']);writer.writerow(['a,b',value])
(out/'summary.json').write_text(json.dumps({'value':value,'run_id':os.environ['WFS_RUN_ID']}))
(out/'report.log').write_text('<script>window.outputXss=true</script>')
print('ARTIFACT_RUN_OK',flush=True)
`,
    'resources/input.txt': 'INPUT_OK',
  };
  await page.getByLabel('完整任务包（ZIP）', { exact: true }).setInputFiles({
    name: 'nested.zip',
    mimeType: 'application/zip',
    buffer: zip(files),
  });
  await page
    .getByRole('button', { name: '上传并检查文件', exact: true })
    .click();
  await page
    .getByLabel('Python 入口', { exact: true })
    .selectOption('src/report_job/main.py');
  await page.getByRole('button', { name: '检查依赖环境', exact: true }).click();
  await expect(
    page.getByRole('button', { name: '发布此版本', exact: true }),
  ).toBeVisible({ timeout: 35000 });
  await page.getByRole('button', { name: '发布此版本', exact: true }).click();
  await page
    .locator('.confirm-modal')
    .getByRole('button', { name: '确认发布', exact: true })
    .click();
  await expect(page.locator('.package-overview')).toContainText('当前版本');
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
