import assert from 'node:assert/strict';
import { readFile, writeFile, unlink } from 'node:fs/promises';
import { parse, compileScript } from '@vue/compiler-sfc';
import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';

const compiledPath = new URL(`.package-workspace-test-${process.pid}.mjs`, import.meta.url);
const mockPath = new URL(`.package-api-test-${process.pid}.mjs`, import.meta.url);
const {descriptor} = parse(await readFile(new URL('../src/components/TaskPackageManager.vue', import.meta.url), 'utf8'));
await writeFile(mockPath, `export const requests=[];
export const api={packages:pid=>new Promise((resolve,reject)=>requests.push({pid,resolve,reject})),
packagePreview:async(pid,version)=>({release:{pid,version,main_file:'main.py',status:'ready'},changes:[]})};`);
const compiled = compileScript(descriptor, {id:'package-regression'}).content
  .replace("'../api'", JSON.stringify(mockPath.href))
  .replace("import LoadingStatus from './LoadingStatus.vue';", 'const LoadingStatus = {};');
await writeFile(compiledPath, compiled);
try {
  const {default:Component} = await import(compiledPath.href);
  const {requests} = await import(mockPath.href);
  let workspace;
  await renderToString(createSSRApp({setup() {
    workspace = Component.setup({confirm:async()=>true,initialPid:''}, {expose(){},emit(){}});
    return ()=>null;
  }}));
  const oldSelection = workspace.select({pid:'old'});
  const newSelection = workspace.select({pid:'new'});
  requests[1].resolve({task:{pid:'new'},versions:[{version:'new-version'}]});
  await newSelection;
  requests[0].reject(new Error('The old task failed'));
  await oldSelection;
  assert.equal(workspace.selected.value.pid, 'new');
  assert.equal(workspace.preview.value.release.version, 'new-version');
  assert.equal(workspace.error.value, '', 'A stale failure must not overwrite the selected task');
  const staleInspect = workspace.inspect('another-old-version');
  workspace.newTask();
  await staleInspect;
  assert.equal(workspace.preview.value, null);
  assert.equal(workspace.loading.value, false, 'Starting a new task must clear the previous loading state');
  console.log('Package workspace ignores stale responses and failures after switching tasks.');
} finally {
  await Promise.all([unlink(compiledPath), unlink(mockPath)]);
}
