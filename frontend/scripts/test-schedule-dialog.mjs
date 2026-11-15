import assert from 'node:assert/strict';
import {readFile,writeFile,unlink} from 'node:fs/promises';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createSSRApp} from 'vue';
import {renderToString} from '@vue/server-renderer';

// Compile the real component tree, including extracted sections, for SSR assertions.
const compiled = new Map();
async function compileComponent(path) {
  if (compiled.has(path.href)) return compiled.get(path.href);
  const target = new URL(`.schedule-component-test-${process.pid}-${compiled.size}.mjs`,import.meta.url);
  compiled.set(path.href,target);
  const {descriptor}=parse(await readFile(path,'utf8'),{filename:path.pathname});
  let source=compileScript(descriptor,{id:`schedule-regression-${compiled.size}`,inlineTemplate:true}).content;
  const imports=[...source.matchAll(/from\s+(['"])(\.[^'"]+)\1/g)];
  for (const [,quote,relative] of imports) {
    let resolved=new URL(relative,path);
    if (relative.endsWith('.vue')) resolved=await compileComponent(resolved);
    else if (!relative.endsWith('.js')) resolved=new URL(relative+'.js',path);
    source=source.replaceAll(quote+relative+quote,JSON.stringify(resolved.href));
  }
  await writeFile(target,source);
  return target;
}
try {
  const compiledPath=await compileComponent(new URL('../src/components/ScheduleDialog.vue',import.meta.url));
  const {default:Dialog}=await import(compiledPath.href);
  const renderDialog=props=>renderToString(createSSRApp(Dialog,props).directive('glass',{}));
  const props={open:true,loading:false,saving:false,task:{id:'second'},error:'配置已被其他操作修改',schedule:{form:{version:1,task_name:'保留的修改',schedule_type:'interval_minutes',interval_minutes:3}}};
  const savedError=await renderDialog(props);
  assert.match(savedError,/配置保存失败/);
  assert.match(savedError,/class="schedule-form"/,'A failed save must retain the form');
  assert.match(savedError,/value="保留的修改"/);
  assert.match(savedError,/id="interval-minutes"[^>]*value="3"/);
  assert.match(savedError,/保存配置/);
  assert.match(savedError,/重新加载配置/);
  const loadError=await renderDialog({...props,schedule:null});
  assert.match(loadError,/配置加载失败/);
  assert.doesNotMatch(loadError,/class="schedule-form"/);
  assert.match(loadError,/重新加载配置/);
  const multiple=await renderDialog({...props,error:'',schedule:{source:'database',form:{schedule_type:'daily_times',daily_times:['05:05','06:55'],owner:'责任人',memory_mb:512}},preview:[{date:'2026-11-15',time:'05:05:00',datetime:'2026-11-15 05:05:00'}]});
  assert.match(multiple,/id="daily-time-0"[^>]*value="05:05"/);
  assert.match(multiple,/id="daily-time-1"[^>]*value="06:55"/);
  assert.match(multiple,/id="task-memory"[^>]*value="512"/);
  assert.match(multiple,/数据库配置 · 1 个后续时间点/);
  assert.match(multiple,/05:05:00/);
  const previewError=await renderDialog({...props,error:'',previewError:'规则尚未填写完整'});
  assert.match(previewError,/预览失败/);
  assert.match(previewError,/规则尚未填写完整/);
  console.log('Split schedule sections retain edits, strategy fields, resources and preview behavior.');
} finally {
  await Promise.all([...compiled.values()].map(path=>unlink(path).catch(error=>{if(error.code!=='ENOENT')throw error;})));
}
