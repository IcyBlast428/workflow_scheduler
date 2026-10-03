import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

// stdlib ZIP writer keeps browser fixtures independent of a packaging library.
function packageZip(files) {
  return execFileSync(process.env.WFS_BROWSER_PYTHON || 'python3', ['-c',
    'import io,json,sys,zipfile; b=io.BytesIO(); z=zipfile.ZipFile(b,"w"); [z.writestr(k,v) for k,v in json.loads(sys.stdin.read()).items()]; z.close(); sys.stdout.buffer.write(b.getvalue())'],
    {input:JSON.stringify(files)});
}

test('multi-file upload, preview, publish, execute, rollback and recycle', async ({page}) => {
  test.setTimeout(100000);
  const errors = []; page.on('pageerror',error => errors.push(error.message));
  await page.goto('/#packages');
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码').fill('browser-test-password');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await expect(page.locator('.package-panel')).toBeVisible();
  await page.locator('.panel-head').getByRole('button',{name:'新增任务',exact:true}).click();
  await page.getByLabel('任务名称',{exact:true}).fill('多文件发布验收');
  await page.getByLabel('任务分类',{exact:true}).fill('发布验收');
  await page.getByLabel('目录名称',{exact:true}).fill('package_browser');
  await page.getByLabel('版本说明',{exact:true}).fill('初始版本');
  await page.getByLabel('完整任务包（ZIP）',{exact:true}).setInputFiles({name:'demo.zip',mimeType:'application/zip',buffer:packageZip({
    'main.py':'from helper import value\nprint(value, flush=True)\n','helper.py':'value="PACKAGE_V1"\n','sql/query.sql':'select 1;'})});
  await page.getByRole('button',{name:'上传并检查文件',exact:true}).click();
  await expect(page.locator('.package-preview')).toContainText('新增 3');
  await page.getByRole('button',{name:'新增 helper.py',exact:true}).click();
  await expect(page.locator('.package-diff pre')).toContainText('+value="PACKAGE_V1"');
  await expect(page.getByLabel('Python 入口',{exact:true})).toHaveValue('main.py');
  const v1 = await page.locator('.package-version strong').first().textContent();
  await page.getByRole('button',{name:'检查依赖环境',exact:true}).click();
  await expect(page.getByRole('button',{name:'发布此版本',exact:true})).toBeVisible({timeout:35000});
  await page.getByRole('button',{name:'发布此版本',exact:true}).click();
  await page.locator('.confirm-modal').getByRole('button',{name:'确认发布',exact:true}).click();
  await expect(page.locator('.package-overview')).toContainText(`当前版本 ${v1}`);
  await page.getByRole('button',{name:'任务列表',exact:true}).click();
  const row = page.locator('.task-table tbody tr').filter({hasText:'多文件发布验收'});
  await expect(row).toContainText('未配置');
  await row.getByRole('button',{name:'触发',exact:true}).click();
  await expect(page.locator('.execution-output')).toContainText('PACKAGE_V1',{timeout:15000});
  await page.locator('.execution-modal').getByTitle('关闭').click();
  await row.getByRole('button',{name:'详情',exact:true}).click();
  await page.getByRole('button',{name:'查看代码',exact:true}).click();
  await expect(page.locator('.source-files')).toContainText('helper.py');
  await page.getByRole('button',{name:'管理代码版本',exact:true}).click();
  await expect(page.locator('.package-overview')).toContainText('多文件发布验收');
  await page.getByText('上传新版本',{exact:true}).click();
  await page.getByLabel('完整任务包（ZIP）',{exact:true}).setInputFiles({name:'demo-v2.zip',mimeType:'application/zip',buffer:packageZip({
    'main.py':'from helper import value\nprint(value, flush=True)\n','helper.py':'value="PACKAGE_V2"\n','README.md':'new version'})});
  await page.getByLabel('版本说明',{exact:true}).fill('第二版本');
  await page.getByRole('button',{name:'上传并预览差异',exact:true}).click();
  await expect(page.locator('.package-preview')).toContainText('新增 1 · 修改 1 · 删除 1');
  await page.getByRole('button',{name:'修改 helper.py',exact:true}).click();
  await expect(page.locator('.package-diff pre')).toContainText('-value="PACKAGE_V1"');
  await expect(page.locator('.package-diff pre')).toContainText('+value="PACKAGE_V2"');
  await page.getByRole('button',{name:'检查依赖环境',exact:true}).click();
  await expect(page.getByRole('button',{name:'发布此版本',exact:true})).toBeVisible({timeout:35000});
  await page.getByRole('button',{name:'发布此版本',exact:true}).click();
  await page.locator('.confirm-modal').getByRole('button',{name:'确认发布',exact:true}).click();
  await expect(page.locator('.package-steps')).toContainText('调度器已确认');
  await page.locator('.package-version').filter({hasText:v1}).click();
  await page.getByRole('button',{name:'回滚到此版本',exact:true}).click();
  await page.locator('.confirm-modal').getByRole('button',{name:'确认回滚',exact:true}).click();
  await expect(page.locator('.package-overview')).toContainText(`当前版本 ${v1}`);
  const downloaded = page.waitForEvent('download');
  await page.getByRole('link',{name:'下载此任务包'}).click();
  expect(await (await downloaded).failure()).toBeNull();
  await page.getByRole('button',{name:'移入回收站',exact:true}).click();
  await page.locator('.confirm-modal').getByRole('button',{name:'移入回收站',exact:true}).click();
  await expect(page.getByRole('button',{name:'恢复任务（暂停）',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'恢复任务（暂停）',exact:true}).click();
  await expect(page.getByText('任务已恢复，自动调度保持暂停。',{exact:true})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:'../data/ui-task-packages-mobile.png',fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({path:'../data/ui-task-packages.png',fullPage:true});
  expect(errors).toEqual([]);
});
