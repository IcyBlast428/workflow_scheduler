import assert from 'node:assert/strict';
import {createRenderer, ref, nextTick} from 'vue';
import {useWorkspaceRefresh} from '../src/composables/useWorkspaceRefresh.js';
import {useRefreshLoop} from '../src/composables/useRefreshLoop.js';
const timers = new Map(); let timer = 0;
const original = {window: globalThis.window, document: globalThis.document, navigator: Object.getOwnPropertyDescriptor(globalThis, 'navigator'), setTimeout, clearTimeout};
globalThis.setTimeout = (fn, delay) => {timers.set(++timer, {fn, delay}); return timer;};
globalThis.clearTimeout = id => timers.delete(id);
const documentTarget = new EventTarget(), windowTarget = new EventTarget();
documentTarget.hidden = false; documentTarget.visibilityState = 'visible';
globalThis.window = windowTarget; globalThis.document = documentTarget;
Object.defineProperty(globalThis, 'navigator', {value: {onLine: true}, configurable: true});
const calls = {dashboard: 0, groups: 0, tasks: 0, system: 0, ids: 0, health: 0};
const token = ref(''), view = ref('dashboard'); let coordinator, healthResolve;
const renderer = createRenderer({insert() {}, remove() {}, createElement: () => ({}), createText: () => ({}), createComment: () => ({}), setText() {}, setElementText() {}, parentNode: () => null, nextSibling: () => null, patchProp() {}});
const flush = async () => {await nextTick(); for (let i = 0; i < 20; i++) await Promise.resolve();};
const app = renderer.createApp({setup() {
  const dashboard = () => {calls.dashboard++; return true;};
  useRefreshLoop({load: dashboard, enabled: () => Boolean(token.value && view.value === 'dashboard'), immediate: false});
  coordinator = useWorkspaceRefresh({token, view, loadDashboard: dashboard, loadTasks: () => {calls.tasks++;}, loadGroups: () => {calls.groups++;},
    loadTaskLogs() {}, loadTaskIds() {}, loadSystemLogs: () => {calls.system++;}, loadSystemIds: () => {calls.ids++;},
    checkBackend: () => {calls.health++; return new Promise(resolve => {healthResolve = resolve;});}, backendStatus: {}, pushToast() {}});
  return () => null;
}});
try {
  app.mount({}); await flush(); assert.equal(calls.dashboard, 0, 'No private workspace reads before authentication');
  token.value = 'session-a'; await flush(); assert.equal(calls.dashboard, 1);
  documentTarget.hidden = true; documentTarget.visibilityState = 'hidden'; documentTarget.dispatchEvent(new Event('visibilitychange'));
  assert.equal(timers.size, 0);
  documentTarget.hidden = false; documentTarget.visibilityState = 'visible'; documentTarget.dispatchEvent(new Event('visibilitychange')); windowTarget.dispatchEvent(new Event('online'));
  await flush(); assert.equal(calls.dashboard, 2, 'The page and its resource must not both reload on resume'); assert.equal(calls.health, 0);
  view.value = 'systemLogs'; await flush(); assert.equal(calls.system, 1); assert.equal(calls.ids, 1); assert.equal(timers.size, 0);
  documentTarget.hidden = true; documentTarget.visibilityState = 'hidden'; documentTarget.dispatchEvent(new Event('visibilitychange'));
  documentTarget.hidden = false; documentTarget.visibilityState = 'visible'; documentTarget.dispatchEvent(new Event('visibilitychange')); await flush();
  assert.equal(calls.system, 2, 'Non-polling system logs still reload after becoming visible'); assert.equal(calls.dashboard, 2);
  const manual = coordinator.refreshActiveView(); assert.equal(coordinator.refreshActiveView(), manual);
  healthResolve(true); await manual; assert.equal(calls.system, 3); assert.equal(calls.health, 1);
  const outdated = coordinator.refreshActiveView(); view.value = 'tasks'; await flush(); healthResolve(true); await outdated;
  assert.equal(calls.tasks, 0, 'A slow health check must not refresh the newly selected page'); assert.equal(calls.groups, 1);
  token.value = ''; await flush(); documentTarget.hidden = true; documentTarget.visibilityState = 'hidden'; documentTarget.dispatchEvent(new Event('visibilitychange'));
  documentTarget.hidden = false; documentTarget.visibilityState = 'visible'; documentTarget.dispatchEvent(new Event('visibilitychange')); await flush();
  assert.equal(calls.system, 3, 'Logged out workspaces do not resume');
  token.value = 'session-b'; view.value = 'dashboard'; await flush(); assert.equal(calls.dashboard, 3, 'A new session initializes the active page once');
  console.log('Workspace initial/resume ownership, system event recovery, explicit refresh and stale navigation checks passed.');
} finally {
  app.unmount(); globalThis.setTimeout = original.setTimeout; globalThis.clearTimeout = original.clearTimeout;
  globalThis.window = original.window; globalThis.document = original.document;
  if (original.navigator) Object.defineProperty(globalThis, 'navigator', original.navigator); else delete globalThis.navigator;
}
