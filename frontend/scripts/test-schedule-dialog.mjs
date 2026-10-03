import assert from 'node:assert/strict';
import { readFile, writeFile, unlink } from 'node:fs/promises';
import { parse, compileScript } from '@vue/compiler-sfc';
import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';

const path=new URL('../src/components/ScheduleDialog.vue',import.meta.url);
const compiledPath=new URL(`.schedule-dialog-test-${process.pid}.mjs`,import.meta.url);
const loadingPath=new URL(`.loading-status-test-${process.pid}.mjs`,import.meta.url);
const {descriptor:loadingDescriptor}=parse(await readFile(new URL('../src/components/LoadingStatus.vue',import.meta.url),'utf8'));
await writeFile(loadingPath,compileScript(loadingDescriptor,{id:'loading-regression',inlineTemplate:true}).content);
const { descriptor }=parse(await readFile(path,'utf8'));
const source=compileScript(descriptor,{id:'schedule-regression',inlineTemplate:true}).content.replace("'../scheduleForm'","'../src/scheduleForm.js'").replace("'./LoadingStatus.vue'",JSON.stringify(loadingPath.href));
await writeFile(compiledPath,source);
try {
  const {default:Dialog}=await import(compiledPath.href);
  const props={open:true,loading:false,saving:false,task:{id:'second'},error:'配置已被其他操作修改',schedule:{form:{version:1,task_name:'保留的修改',schedule_type:'interval_minutes',interval_minutes:3}}};
  const savedError=await renderToString(createSSRApp(Dialog,props));
  assert.match(savedError,/配置保存失败/);
  assert.match(savedError,/class="schedule-form"/,'A failed save must retain the form');
  assert.match(savedError,/value="保留的修改"/);
  assert.match(savedError,/id="interval-minutes"[^>]*value="3"/);
  assert.match(savedError,/保存配置/);
  assert.match(savedError,/重新加载配置/);
  const loadError=await renderToString(createSSRApp(Dialog,{...props,schedule:null}));
  assert.match(loadError,/配置加载失败/);
  assert.doesNotMatch(loadError,/class="schedule-form"/);
  assert.match(loadError,/重新加载配置/);
  console.log('Actual schedule dialog rendering retains edits after save errors and supports load retry.');
} finally { await Promise.all([unlink(compiledPath),unlink(loadingPath)]); }
