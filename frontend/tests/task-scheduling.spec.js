import { test, expect } from '@playwright/test';

test('task row styling and daily paired times survive saving and reopening', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/#tasks');
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码').fill('browser-test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  const row = page
    .locator('.task-table tbody tr')
    .filter({ hasText: 'acceptance__slow' });
  await expect(row).toBeVisible();
  await expect(page.locator('.panel > .loading-status')).toHaveAttribute(
    'aria-busy',
    'false',
  );
  await expect(row).not.toContainText('尚未配置调度策略');
  await expect(row.locator('.action-cell .favorite-button')).toBeVisible();
  await expect(row.locator('.task-name-cell .favorite-button')).toHaveCount(0);
  await row.hover();
  await expect
    .poll(() =>
      row
        .locator('td')
        .evaluateAll(
          (cells) =>
            new Set(cells.map((cell) => getComputedStyle(cell).backgroundColor))
              .size,
        ),
    )
    .toBe(1);
  await row.getByRole('button', { name: '更多', exact: true }).click();
  await page
    .locator('.action-menu')
    .getByRole('button', { name: '配置', exact: true })
    .click();
  const dialog = page.locator('.schedule-modal');
  const enabled = dialog.getByLabel('启用自动调度');
  await expect(enabled).toBeEnabled();
  await enabled.uncheck();
  const cards = await dialog
    .locator('.schedule-overview > .runtime-card')
    .evaluateAll((elements) =>
      elements.map((el) => {
        const r = el.getBoundingClientRect();
        return { x: r.x, y: r.y, right: r.right, bottom: r.bottom };
      }),
    );
  expect(Math.abs(cards[0].y - cards[1].y)).toBeLessThan(2);
  expect(cards[1].x).toBeGreaterThan(cards[0].right);
  const inputs = await dialog
    .locator('#schedule-owner, #task-description')
    .evaluateAll((elements) =>
      elements.map((el) => el.getBoundingClientRect().y),
    );
  expect(Math.abs(inputs[0] - inputs[1])).toBeLessThan(2);
  const policyBox = await dialog.locator('.schedule-editor').boundingBox();
  expect(policyBox.y).toBeGreaterThan(
    Math.max(...cards.map((card) => card.bottom)),
  );
  await dialog.getByRole('button', { name: /固定时间/ }).click();
  await dialog.getByLabel('策略类型').selectOption('daily_times');
  await dialog.getByLabel('时间点 1', { exact: true }).fill('05:05');
  await dialog.getByRole('button', { name: '添加时间点', exact: true }).click();
  await dialog.getByLabel('时间点 2', { exact: true }).fill('06:55');
  const times = dialog.locator('.preview-time > span');
  await expect
    .poll(async () => [...new Set(await times.allTextContents())].sort())
    .toEqual(['05:05:00', '06:55:00']);
  // Changing an existing array entry must refresh the preview as well.
  await dialog.getByLabel('时间点 2', { exact: true }).fill('07:25');
  await expect
    .poll(async () => [...new Set(await times.allTextContents())].sort())
    .toEqual(['05:05:00', '07:25:00']);
  await dialog.getByLabel('时间点 2', { exact: true }).fill('06:55');
  await dialog.getByRole('button', { name: '保存配置', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const toast = page
    .locator('.toast.success')
    .filter({ hasText: '任务配置已保存' });
  await expect(toast).toBeVisible();
  expect(
    await toast.evaluate((el) => getComputedStyle(el).borderLeftColor),
  ).toBe('rgb(212, 175, 101)');
  await row.getByRole('button', { name: '更多', exact: true }).click();
  await page
    .locator('.action-menu')
    .getByRole('button', { name: '配置', exact: true })
    .click();
  await expect(dialog.getByLabel('策略类型')).toHaveValue('daily_times');
  await expect(dialog.getByLabel('时间点 1', { exact: true })).toHaveValue(
    '05:05',
  );
  await expect(dialog.getByLabel('时间点 2', { exact: true })).toHaveValue(
    '06:55',
  );
  await expect(enabled).not.toBeChecked();
  await expect
    .poll(async () => [...new Set(await times.allTextContents())].sort())
    .toEqual(['05:05:00', '06:55:00']);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  const mobileCards = await dialog
    .locator('.schedule-overview > .runtime-card')
    .evaluateAll((elements) =>
      elements.map((el) => {
        const r = el.getBoundingClientRect();
        return { x: r.x, y: r.y, bottom: r.bottom };
      }),
    );
  expect(mobileCards[1].y).toBeGreaterThan(mobileCards[0].bottom);
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
});
