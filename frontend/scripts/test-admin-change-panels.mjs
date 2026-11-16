import assert from 'node:assert/strict';
import { readFile, writeFile, unlink } from 'node:fs/promises';
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc';
import { createSSRApp, createRenderer, nextTick, reactive } from 'vue';
import { renderToString } from '@vue/server-renderer';

const temporary = [];
async function moduleFile(name, source) {
  const path = new URL(`.panels-${process.pid}-${name}.mjs`, import.meta.url);
  temporary.push(path);
  await writeFile(path, source);
  return path;
}
try {
  const mockPath = await moduleFile('api', `
    export const requests=[];
    const request=(kind)=>new Promise((resolve,reject)=>requests.push({kind,resolve,reject}));
    export const matrixRequests=[];
    export const api={operationalPolicy:request,notificationQueue:()=>request('notifications'),backupStatus:()=>request('backup'),recentExecutionMatrix:async limit=>{matrixRequests.push(limit);return {limit,tasks:[]};},gitlabState:()=>request('gitlab-state'),gitlabTasks:()=>request('gitlab-tasks')};
  `);
  async function component(name) {
    const { descriptor } = parse(await readFile(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8'));
    const script = compileScript(descriptor, { id: name });
    const source = script.content
      .replace("'../api'", JSON.stringify(mockPath.href))
      .replace("'../composables/useRefreshLoop.js'", "'../src/composables/useRefreshLoop.js'")
      .replace("'../workspacePreferences.js'", "'../src/workspacePreferences.js'")
      .replace("'../executionLabels'", "'../src/executionLabels.js'")
      .replace("'../composables/useUnsavedChanges'", "'../src/composables/useUnsavedChanges.js'");
    const scriptPath = await moduleFile(name, source);
    const template = compileTemplate({ source: descriptor.template.content, filename: `${name}.vue`, id: name,
      compilerOptions: { bindingMetadata: script.bindings } });
    assert.deepEqual(template.errors, []);
    const templatePath = await moduleFile(`${name}-render`, template.code);
    const result = (await import(scriptPath.href)).default;
    result.render = (await import(templatePath.href)).render;
    return result;
  }
  const Changes = await component('GitlabTaskChanges');
  // No TaskTable is mounted: every kind must still have a visible, actionable card.
  for (const [kind, label, action] of [
    ['new', '新任务 · 待发布', '审查并发布'],
    ['update', '原任务 · 待更新', '审查并发布'],
    ['delete', '原任务 · 待确认删除', '查看删除变更'],
    ['recover', '原任务 · 待恢复关联', '恢复原任务'],
  ]) {
    const html = await renderToString(createSSRApp({ ...Changes, setup(props, context) {
      const state = Changes.setup(props, context);
      state.state.value = { enabled: true, complete: true, items: [{ id: kind, pid: 'original', kind,
        task_name: '原目录任务', group_name: 'group', folder_name: 'original', sha: 'abcdef123456', file_count: 1 }] };
      return state;
    } }));
    assert.ok(html.includes('1 项 GitLab 变更待处理'), kind);
    assert.ok(html.includes(label), kind);
    assert.ok(html.includes('<h3>原目录任务</h3>'), kind);
    assert.ok(html.includes(action), kind);
    assert.ok(!html.includes('返回任务列表首页'), kind);
    const collapsed = await renderToString(createSSRApp({ ...Changes, setup(props, context) {
      const state = Changes.setup(props, context);
      state.state.value = { enabled: true, items: [{ id: kind, kind, sha: 'abc', task_name: '任务' }] };
      assert.equal(state.expanded.value, true);
      state.toggleExpanded();
      // A subsequent polling response and an error must respect the manual choice.
      state.state.value = { ...state.state.value, items: [...state.state.value.items] };
      state.error.value = '连接暂不可用';
      assert.equal(state.expanded.value, false);
      state.toggleExpanded();
      assert.equal(state.expanded.value, true);
      state.toggleExpanded();
      return state;
    } }));
    assert.ok(collapsed.includes('aria-expanded="false"'), kind);
    assert.match(collapsed, /class="changes-content" style="display:none;"/);
    assert.ok(collapsed.includes('查看待处理变更'), kind);
  }
  const Workbench = await component('OperationalWorkbench');
  const { requests } = await import(mockPath.href);
  async function setup(section) {
    let state;
    const props = { section };
    await renderToString(createSSRApp({ setup() {
      state = Workbench.setup(props, { expose() {} });
      return () => null;
    } }));
    return { state, props };
  }
  const settle = async () => { await Promise.resolve(); await Promise.resolve(); };
  const runtime = await setup('runtime');
  assert.deepEqual(requests.map(r => r.kind), ['groups', 'notifications']);
  requests.shift().resolve({ revision: 1, quotas: { daily: 2 } });
  requests.shift().resolve([{ id: 1, status: 'unknown' }]);
  await settle();
  assert.equal(runtime.state.error.value, '');
  assert.equal(runtime.state.loaded.value, true);
  assert.deepEqual(runtime.state.quotas.value, [{ group: 'daily', limit: 2 }]);
  assert.equal(runtime.state.alerts.value[0].outcome, 'confirmed_sent');

  const release = await setup('release');
  assert.deepEqual(requests.map(r => r.kind), ['release']);
  requests.shift().resolve({ revision: 1 }); // older/missing optional branch list
  await settle();
  assert.equal(release.state.error.value, '');
  assert.equal(release.state.branches.value, '*');
  assert.equal(release.state.loaded.value, true);
  const stale = release.state.load();
  const old = requests.shift();
  release.props.section = 'runtime';
  const current = release.state.load();
  requests.shift().resolve({ quotas: { current: 3 } });
  await current;
  old.reject(new Error('stale release failure'));
  await stale;
  assert.equal(release.state.error.value, '');
  assert.deepEqual(release.state.quotas.value, [{ group: 'current', limit: 3 }]);

  const storage = await setup('storage');
  assert.deepEqual(requests.map(r => r.kind), ['backup']);
  requests.shift().resolve({ backup: { path: 'archive.zip' } });
  await settle();
  assert.equal(storage.state.backup.value.backup.path, 'archive.zip');
  const Updates = await component('GitlabUpdates');
  let updates;
  const updateHtml = await renderToString(createSSRApp({ ...Updates, async setup(props, context) {
    updates = Updates.setup(props, context);
    const refresh = updates.refresh();
    assert.deepEqual(requests.map(r => r.kind), ['gitlab-state', 'gitlab-tasks']);
    requests.shift().resolve({ enabled: true, pending_merge: 0, pending_release: 0, count: 0, items: [], warnings: ['未设置平台部署基线'], checked_at: 1 });
    requests.shift().resolve({ enabled: true, complete: true, items: [{ kind: 'new', pid: 'original' }] });
    await refresh;
    return updates;
  } }));
  assert.ok(updateHtml.includes('已部署版本差异 0'));
  assert.ok(updateHtml.includes('任务待处理 1'));
  assert.ok(updateHtml.includes('前往任务列表'));
  assert.ok(updateHtml.includes('暂无可比较的版本差异'));
  assert.ok(updateHtml.includes('新任务请到任务列表审查发布'));
  assert.ok(!updateHtml.includes('当前没有可展示的更新'));
  const failedTasks = updates.refresh();
  requests.shift().resolve({ ...updates.state.value, checked_at: 2 });
  requests.shift().reject(new Error('任务扫描读取失败'));
  await failedTasks;
  assert.equal(updates.state.value.checked_at, 2);
  assert.equal(updates.taskSummaryLabel.value, '任务检查异常');
  assert.equal(updates.taskError.value, '任务扫描读取失败');
  const Recent = await component('RecentExecutionMatrix');
  const { matrixRequests } = await import(mockPath.href);
  const originalGlobals = Object.fromEntries(['window', 'document', 'localStorage'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const apps = [];
  try {
    const saved = new Map();
    globalThis.window = new EventTarget();
    globalThis.document = Object.assign(new EventTarget(), { hidden: false, visibilityState: 'visible' });
    globalThis.localStorage = { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) };
    const renderer = createRenderer({ insert() {}, remove() {}, createComment: () => ({}), parentNode: () => null, nextSibling: () => null });
    function mount(userKey) {
      const props = reactive({ active: false, userKey });
      let state;
      const app = renderer.createApp({ setup() {
        state = Recent.setup(props, { expose() {}, emit() {} });
        return () => null;
      } });
      app.mount({});
      apps.push(app);
      return { state, props };
    }
    const first = mount('admin');
    assert.equal(first.state.limit.value, 10);
    first.state.limit.value = 25;
    await nextTick();
    assert.equal(matrixRequests.at(-1), 25);
    first.props.userKey = 'viewer';
    assert.equal(first.state.limit.value, 10);
    first.props.userKey = 'admin';
    assert.equal(first.state.limit.value, 25);
    apps.pop().unmount();
    const revisited = mount('admin');
    assert.equal(revisited.state.limit.value, 25, 'Reopening restores the saved count');
    revisited.state.limit.value = 10;
    await nextTick();
    assert.equal(matrixRequests.at(-1), 10);
    assert.equal(mount('admin').state.limit.value, 10);
    saved.set('wfs:recent-results:v1:corrupt', '{broken');
    assert.equal(mount('corrupt').state.limit.value, 10);
    saved.set('wfs:recent-results:v1:invalid', '{"limit":1000}');
    assert.equal(mount('invalid').state.limit.value, 10);
    globalThis.localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
    const unavailable = mount('blocked');
    assert.equal(unavailable.state.limit.value, 10);
    unavailable.state.limit.value = 25;
    await nextTick();
    assert.equal(unavailable.state.error.value, '');
  } finally {
    apps.forEach(app => app.unmount());
    for (const [key, descriptor] of Object.entries(originalGlobals)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
  console.log('Pending changes respect manual collapse; recent-result counts default to 10 and persist per account with safe storage fallback.');
  console.log('All GitLab change kinds render without task rows; admin sections load independently and tolerate missing branches.');
} finally {
  await Promise.all(temporary.map(path => unlink(path)));
}
