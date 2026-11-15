import {test, expect} from '@playwright/test';
import {detailTab} from './navigation-helpers.js';

async function openTask(page) {
  await page.goto('/#tasks');
  await page.getByLabel('用户名', {exact: true}).fill('admin');
  await page.getByLabel('密码', {exact: true}).fill('browser-test-password');
  await page.getByRole('button', {name: '登录', exact: true}).click();
  await page.locator('.task-table tbody tr').filter({hasText: 'acceptance__slow'}).locator('.task-name-link').click();
  await expect(page.locator('.task-metadata')).toBeVisible();
  await expect(page.getByRole('button', {name: '刷新详情', exact: true})).toBeEnabled();
}

async function expectWithinBody(control, body) {
  await control.scrollIntoViewIfNeeded();
  const bounds = await control.boundingBox(), viewport = await body.boundingBox();
  expect(bounds.y).toBeGreaterThanOrEqual(viewport.y);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(viewport.y + viewport.height);
}

test('short and narrow task dialogs keep publication and source controls reachable', async ({page}) => {
  await openTask(page);
  const dialog = page.locator('.task-workbench'), body = dialog.locator('.task-detail-body');
  for (const viewport of [{width: 320, height: 568}, {width: 844, height: 390}]) {
    await page.setViewportSize(viewport);
    await detailTab(page, '代码版本');
    const reason = dialog.getByLabel('本次发布说明', {exact: true});
    await expect(reason).toBeVisible();
    expect((await dialog.locator('.detail-panels').boundingBox()).height).toBeGreaterThan(200);
    await expectWithinBody(reason, body);
    const close = await dialog.locator(':scope > .modal-head').getByTitle('关闭').boundingBox();
    expect(close.y).toBeGreaterThanOrEqual(0);
    expect(close.y + close.height).toBeLessThanOrEqual(viewport.height);
    await detailTab(page, '查看代码');
    await expect(dialog.locator('.source-code')).toContainText('print');
    await expectWithinBody(dialog.getByRole('button', {name: '下一页内容', exact: true}), body);
    expect(await body.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  }
});

test('release gates, release notes and long SDK hashes retain space at mobile width', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await openTask(page);
  await detailTab(page, '代码版本');
  const preview = page.locator('.release-preview');
  await expect(preview.locator('.release-gates')).toBeVisible();
  const spacing = await preview.evaluate(element => {
    const gates = element.querySelector('.release-gates').getBoundingClientRect();
    const label = element.querySelector('.release-reason');
    const input = label.querySelector('input').getBoundingClientRect();
    const text = document.createRange();
    text.selectNode(label.firstChild);
    return {section: label.getBoundingClientRect().top - gates.bottom, field: input.top - text.getBoundingClientRect().bottom};
  });
  expect(spacing.section).toBeGreaterThanOrEqual(12);
  expect(spacing.field).toBeGreaterThanOrEqual(6);
  const sdk = preview.locator('.release-checklist .mono');
  await expect(sdk).toContainText('候选 SDK');
  expect(await sdk.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
});

test('desktop task toolbar remains fixed during a delayed detail refresh', async ({page}) => {
  await page.setViewportSize({width: 1440, height: 900});
  await openTask(page);
  const dialog = page.locator('.task-workbench'), toolbar = dialog.locator('.detail-toolbar');
  const initialDialog = await dialog.boundingBox(), initialToolbar = await toolbar.boundingBox();
  let release;
  const gate = new Promise(resolve => {release = resolve;});
  await page.route('**/api/taskinfo/detail?*', async route => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({response});
  });
  try {
    await dialog.getByRole('button', {name: '刷新详情', exact: true}).click();
    await expect(dialog.getByRole('button', {name: '刷新中…', exact: true})).toBeDisabled();
    await expect(dialog.locator('.task-detail-body > .loading-status')).toHaveClass(/is-loading/);
    expect(await toolbar.boundingBox()).toEqual(initialToolbar);
    expect(await dialog.boundingBox()).toEqual(initialDialog);
  } finally {
    release();
  }
  await expect(dialog.getByRole('button', {name: '刷新详情', exact: true})).toBeEnabled();
  expect(await toolbar.boundingBox()).toEqual(initialToolbar);
});


test('nested release trial settings fit inside a narrow task dialog', async ({page}) => {
  await page.setViewportSize({width: 320, height: 568});
  await openTask(page);
  await detailTab(page, '代码版本');
  const release = page.locator('.release-body');
  await release.locator('summary').filter({hasText: '试运行设置与执行请求'}).click();
  const operations = release.locator('.task-operations');
  await expect(operations.getByRole('button', {name: '保存运行策略', exact: true})).toBeEnabled();
  const overflow = await operations.evaluate(element => [element, ...element.querySelectorAll('.filter-grid')]
    .map(item => ({width: item.clientWidth, scrollWidth: item.scrollWidth})));
  for (const bounds of overflow) expect(bounds.scrollWidth).toBeLessThanOrEqual(bounds.width + 1);
  await expectWithinBody(operations.getByRole('button', {name: '保存运行策略', exact: true}), page.locator('.task-detail-body'));
});
