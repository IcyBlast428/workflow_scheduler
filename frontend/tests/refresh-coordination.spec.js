import {test, expect} from '@playwright/test';

async function setupClock(page) {
  const now = new Date();
  await page.clock.install({time: now}); await page.clock.pauseAt(now);
  await page.addInitScript(() => {
    window.refreshTestState = {hidden: false, online: true};
    Object.defineProperty(document, 'hidden', {configurable: true, get: () => window.refreshTestState.hidden});
    Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => window.refreshTestState.hidden ? 'hidden' : 'visible'});
    Object.defineProperty(navigator, 'onLine', {configurable: true, get: () => window.refreshTestState.online});
  });
}
async function environment(page, hidden, online) {
  await page.evaluate(({hidden, online}) => {
    window.refreshTestState.hidden = hidden; window.refreshTestState.online = online;
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new Event(online ? 'online' : 'offline'));
  }, {hidden, online});
}
async function login(page, hash = 'dashboard', username = 'admin') {
  await page.goto('/#' + hash);
  await page.getByLabel('用户名', {exact: true}).fill(username);
  await page.getByLabel('密码', {exact: true}).fill('browser-test-password');
  await page.getByRole('button', {name: '登录', exact: true}).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}
function countResource(page, pathname) {
  let count = 0;
  page.on('request', request => {if (new URL(request.url()).pathname === pathname) count++;});
  return () => count;
}

test('dashboard resumes once even when health recovers later and ignores hidden or offline timers', async ({page}) => {
  await setupClock(page);
  const reads = countResource(page, '/api/taskinfo/dashboard');
  let holdHealth = false, releaseHealth;
  await page.route('**/api/user/health', async route => {
    if (holdHealth) await new Promise(resolve => {releaseHealth = resolve;});
    await route.fulfill({json: {code: 20000, data: {healthy: true}}});
  });
  await login(page);
  await expect(page.locator('.cpu-timeline')).toBeVisible();
  await expect(page.locator('.dashboard-loading')).toHaveCount(0);
  expect(reads()).toBe(1);
  await environment(page, true, true); await page.clock.fastForward(60001); expect(reads()).toBe(1);
  await environment(page, false, false); await page.clock.fastForward(60001); expect(reads()).toBe(1);
  holdHealth = true;
  await environment(page, false, true);
  await expect.poll(reads).toBe(2); await expect.poll(() => Boolean(releaseHealth)).toBe(true);
  const readiness = page.waitForResponse(response => new URL(response.url()).pathname === '/api/user/ready');
  holdHealth = false; releaseHealth(); await (await readiness).finished();
  await page.clock.runFor(200);
  expect(reads()).toBe(2, 'The former App-level recovery must not load the dashboard again after health completes');
  await environment(page, false, true); await page.clock.runFor(200); expect(reads()).toBe(2);
});

test('task navigation and resume use one state read while hidden workspaces retain their data', async ({page}) => {
  await setupClock(page);
  const states = countResource(page, '/api/taskinfo/state'), dashboards = countResource(page, '/api/taskinfo/dashboard');
  await login(page, 'tasks'); await expect(page.locator('.task-table tbody tr')).not.toHaveCount(0);
  await expect(page.locator('.task-loading')).toHaveAttribute('aria-busy', 'false');
  expect(states()).toBe(1); expect(dashboards()).toBe(0, 'Login must not eagerly fetch an unopened dashboard');
  const firstTask = await page.locator('.task-table tbody tr').first().innerText();
  await environment(page, true, true); await page.clock.fastForward(10001); expect(states()).toBe(1);
  await environment(page, false, true); await expect.poll(states).toBe(2); await page.clock.runFor(200); expect(states()).toBe(2);
  await page.getByRole('navigation', {name: '工作区导航'}).getByRole('button', {name: '总览', exact: true}).click();
  await expect(page.locator('.cpu-timeline')).toBeVisible(); await expect.poll(dashboards).toBe(1);
  await page.getByRole('navigation', {name: '工作区导航'}).getByRole('button', {name: '任务列表', exact: true}).click();
  await expect.poll(states).toBe(3); await expect(page.locator('.task-table tbody tr').first()).toContainText(firstTask.split('\n')[0]);
  await page.clock.runFor(200); expect(states()).toBe(3);
});

test('system events load and resume without an unused event-polling loop', async ({page}) => {
  await setupClock(page);
  const systems = countResource(page, '/api/taskinfo/systemLogs'), events = countResource(page, '/api/taskinfo/events');
  await login(page, 'systemLogs'); await expect(page.getByRole('heading', {name: '平台事件', exact: true})).toBeVisible();
  await expect.poll(systems).toBe(1); expect(events()).toBe(0);
  await page.clock.fastForward(10001); expect(systems()).toBe(1); expect(events()).toBe(0);
  await environment(page, true, true); await environment(page, false, true);
  await expect.poll(systems).toBe(2); await page.clock.runFor(200); expect(systems()).toBe(2); expect(events()).toBe(0);
});

test('historical timeline resumes once, cancels live polling and restarts it on request', async ({page}) => {
  await setupClock(page);
  const reads = countResource(page, '/api/taskinfo/matrix');
  await login(page, 'matrix?tab=timeline'); await expect(page.locator('.matrix-surface')).toBeVisible(); await expect.poll(reads).toBe(1);
  const live = page.getByLabel('实时跟随今天');
  const refresh = page.locator('.matrix-filters').getByRole('button', {name: '刷新', exact: true});
  await live.uncheck(); await expect.poll(reads).toBe(2);
  await expect(refresh).toBeEnabled();
  await page.clock.fastForward(20001); expect(reads()).toBe(2);
  await environment(page, true, true);
  const recovered = page.waitForResponse(response => new URL(response.url()).pathname === '/api/taskinfo/matrix');
  await environment(page, false, true); await (await recovered).finished();
  await expect.poll(reads).toBe(3); await page.clock.fastForward(20001); expect(reads()).toBe(3);
  await live.check(); await expect.poll(reads).toBe(4);
  // Network completion uses real time even when the browser clock is paused.
  // Finish the forced read before advancing the restored periodic timer.
  await expect(refresh).toBeEnabled();
  await page.clock.fastForward(10001); await expect.poll(reads).toBe(5);
});
