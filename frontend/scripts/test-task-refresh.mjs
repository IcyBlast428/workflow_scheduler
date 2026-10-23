import assert from 'node:assert/strict';
import { readFile, writeFile, unlink } from 'node:fs/promises';
import { effectScope, ref, nextTick } from 'vue';

const modulePath = new URL(`.task-refresh-${process.pid}.mjs`, import.meta.url);
const mockPath = new URL(
  `.task-refresh-api-${process.pid}.mjs`,
  import.meta.url,
);
await writeFile(
  mockPath,
  `export const requests=[];
export const api={taskState:()=>new Promise((resolve,reject)=>requests.push({resolve,reject}))};`,
);
await writeFile(
  modulePath,
  (
    await readFile(
      new URL('../src/composables/useTaskWorkspace.js', import.meta.url),
      'utf8',
    )
  )
    .replace("'../api.js'", JSON.stringify(mockPath.href))
    .replace(
      "'../workspacePreferences.js'",
      "'../src/workspacePreferences.js'",
    ),
);
globalThis.localStorage = { getItem: () => null, setItem() {} };
const scope = effectScope();
try {
  const { useTaskWorkspace } = await import(modulePath.href);
  const { requests } = await import(mockPath.href);
  const identity = ref('admin');
  const workspace = scope.run(() =>
    useTaskWorkspace(() => identity.value, {
      markBackendHealthy() {},
      handleRequestFailure: async (error, { state }) => {
        state.error = error.message;
      },
      requestConfirm() {},
      pushToast() {},
    }),
  );
  // The foreground result becomes stale while a live update is still in flight.
  const initial = workspace.loadTasks();
  const background = workspace.loadTasks(false, { silent: true });
  requests[0].resolve({ items: [{ id: 'old' }], total: 1 });
  await initial;
  assert.equal(workspace.tasks.loading, true);
  requests[1].resolve({ items: [{ id: 'new' }], total: 1 });
  await background;
  assert.equal(
    workspace.tasks.loading,
    false,
    'A silent refresh must complete the superseded foreground spinner',
  );
  assert.equal(workspace.tasks.items[0].id, 'new');

  const older = workspace.loadTasks();
  const newest = workspace.loadTasks(false, { silent: true });
  requests[3].reject(new Error('Refresh failed'));
  await newest;
  assert.equal(workspace.tasks.loading, false);
  requests[2].resolve({ items: [{ id: 'stale' }] });
  await older;
  assert.equal(
    workspace.tasks.items[0].id,
    'new',
    'A stale result must not replace retained rows',
  );
  assert.equal(workspace.tasks.error, 'Refresh failed');

  const outgoing = workspace.loadTasks();
  identity.value = 'viewer';
  await nextTick();
  assert.equal(workspace.tasks.loading, false);
  requests[4].resolve({ items: [{ id: 'admin-only' }] });
  await outgoing;
  assert.deepEqual(workspace.tasks.items, []);
  console.log(
    'Task refresh overlap, stale failures and account changes clear loading without replacing current data.',
  );
} finally {
  scope.stop();
  await Promise.all([unlink(modulePath), unlink(mockPath)]);
}
