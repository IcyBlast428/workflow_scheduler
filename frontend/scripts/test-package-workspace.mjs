import assert from 'node:assert/strict';
import { readFile, writeFile, unlink } from 'node:fs/promises';
import { parse, compileScript } from '@vue/compiler-sfc';
import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
const compiledPath = new URL(`.package-workspace-test-${process.pid}.mjs`, import.meta.url);
const mockPath = new URL(`.package-api-test-${process.pid}.mjs`, import.meta.url);
const { descriptor } = parse(await readFile(new URL('../src/components/TaskReleaseDialog.vue', import.meta.url), 'utf8'));
await writeFile(mockPath, `export const requests=[],actions=[],controls={failure:null}; export const api={packagePreview:(pid,version)=>new Promise((resolve,reject)=>requests.push({pid,version,resolve,reject})),gitlabTaskAction:async value=>actions.push(value),scanGitlab:async()=>actions.push('scan'),packageAction:async value=>{actions.push(value);if(controls.failure)throw new Error(controls.failure);return {version:'rebuilt'};},gitlabTasks:async()=>({items:[]}),packages:async()=>({task:{revision:3,active_version:'v1'},versions:[]})};`);
const compiled = compileScript(descriptor, {id:'release-regression'}).content
  .replace("'../api'", JSON.stringify(mockPath.href))
  .replace("'../composables/useRefreshLoop.js'", "'../src/composables/useRefreshLoop.js'")
  .replace("'../composables/useUnsavedChanges'", "'../src/composables/useUnsavedChanges.js'")
  .replace("import LoadingStatus from './LoadingStatus.vue';", 'const LoadingStatus = {};')
  .replace("import ModalShell from './ModalShell.vue';", 'const ModalShell = {};');
await writeFile(compiledPath, compiled);
try {
  const { default: Component } = await import(compiledPath.href);
  const { requests, actions, controls } = await import(mockPath.href);
  const emitted=[];
  let workspace;
  await renderToString(createSSRApp({setup() {
    workspace = Component.setup({confirm:async()=>true,pid:''}, {expose(){},emit(name){emitted.push(name);}});
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
  const previousWindow=globalThis.window;
  try {
    globalThis.window={dispatchEvent(){}};
    workspace.candidate.value={id:'recover-original',path:'app/jobs/group/original',recovery:{pid:'original-id'}};
    await workspace.recoverIdentity();
    assert.deepEqual(actions,[{action:'recover',id:'recover-original'},'scan']);
    assert.ok(emitted.includes('changed'));
    assert.ok(emitted.includes('close'));
  } finally {
    if(previousWindow===undefined)delete globalThis.window;
    else globalThis.window=previousWindow;
  }
  requests.length=0;actions.length=0;
  const preview=(version,status='staged',requirements=['requests'])=>({release:{version,status,requirements,requirements_source:'auto',main_file:'main.py'}});
  const initial=workspace.inspect('candidate');requests.shift().resolve(preview('candidate'));await initial;
  assert.equal(workspace.dependencyText.value,'requests');
  workspace.dependencyText.value='requests\npandas';
  const refresh=workspace.inspect('candidate');requests.shift().resolve(preview('candidate'));await refresh;
  assert.equal(workspace.dependencyText.value,'requests\npandas','Refresh must preserve unsubmitted package edits');
  controls.failure='仓库连接失败';
  await workspace.prepare();
  assert.equal(workspace.dependencyForm.dirty.value,true,'Rejected save must keep the draft dirty');
  assert.equal(actions[0].requirements,'requests\npandas');
  controls.failure=null;
  const preparing=workspace.prepare();
  for(let i=0;i<20&&!requests.length;i++)await Promise.resolve();
  requests.shift().resolve(preview('candidate','preparing',['requests','pandas']));await preparing;
  assert.equal(workspace.dependencyText.value,'requests\npandas');
  assert.equal(workspace.dependencyForm.dirty.value,false);
  const next=workspace.inspect('another');requests.shift().resolve(preview('another'));await next;
  const automatic=workspace.prepare();
  for(let i=0;i<20&&!requests.length;i++)await Promise.resolve();
  assert.equal(Object.hasOwn(actions.at(-1),'requirements'),false,'Unedited automatic plan must stay automatic');
  requests.shift().resolve(preview('another','ready'));await automatic;
  workspace.record.value={revision:3,active_version:'another'};
  assert.equal(workspace.canRebuild.value,true);
  const oldWindow=globalThis.window;
  try{
    globalThis.window={dispatchEvent(){}};
    const rebuilding=workspace.rebuild();
    for(let i=0;i<30&&!requests.length;i++)await Promise.resolve();
    assert.deepEqual(actions.at(-1),{action:'rebuild',pid:'',version:'another',revision:3});
    requests.shift().resolve(preview('rebuilt'));await rebuilding;
    assert.equal(workspace.canPrepare.value,true);
    assert.equal(workspace.preview.value.release.version,'rebuilt');
  }finally{if(oldWindow===undefined)delete globalThis.window;else globalThis.window=oldWindow;}
  console.log('Release workspace preserves dependency drafts, installs overrides and rebuilds immutable versions.');
} finally { await Promise.all([unlink(compiledPath), unlink(mockPath)]); }
