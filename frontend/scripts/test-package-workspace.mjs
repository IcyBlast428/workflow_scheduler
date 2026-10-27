import assert from 'node:assert/strict';
import { readFile, writeFile, unlink } from 'node:fs/promises';
import { parse, compileScript } from '@vue/compiler-sfc';
import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
const compiledPath = new URL(`.package-workspace-test-${process.pid}.mjs`, import.meta.url);
const mockPath = new URL(`.package-api-test-${process.pid}.mjs`, import.meta.url);
const { descriptor } = parse(await readFile(new URL('../src/components/TaskReleaseDialog.vue', import.meta.url), 'utf8'));
await writeFile(mockPath, `export const requests=[]; export const api={packagePreview:(pid,version)=>new Promise((resolve,reject)=>requests.push({pid,version,resolve,reject}))};`);
const compiled = compileScript(descriptor, {id:'release-regression'}).content
  .replace("'../api'", JSON.stringify(mockPath.href))
  .replace("import LoadingStatus from './LoadingStatus.vue';", 'const LoadingStatus = {};')
  .replace("import ModalShell from './ModalShell.vue';", 'const ModalShell = {};');
await writeFile(compiledPath, compiled);
try {
  const { default: Component } = await import(compiledPath.href);
  const { requests } = await import(mockPath.href);
  let workspace;
  await renderToString(createSSRApp({setup() {
    workspace = Component.setup({confirm:async()=>true,pid:''}, {expose(){},emit(){}});
    return ()=>null;
  }}));
  workspace.preview.value = {release:{version:'v1'}};
  const oldFile = workspace.inspectFile('old.py');
  const newFile = workspace.inspectFile('new.py');
  requests[1].resolve({diff:'+new'}); await newFile;
  requests[0].reject(new Error('stale file failed')); await oldFile;
  assert.equal(workspace.path.value, 'new.py');
  assert.equal(workspace.diff.value, '+new');
  assert.equal(workspace.error.value, '');
  assert.equal(workspace.diffLoading.value, false);
  console.log('GitLab release viewer ignores stale file responses and failures.');
} finally { await Promise.all([unlink(compiledPath), unlink(mockPath)]); }
