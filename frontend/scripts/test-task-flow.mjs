import assert from 'node:assert/strict';
import {readFile,writeFile,unlink} from 'node:fs/promises';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createSSRApp} from 'vue';
import {renderToString} from '@vue/server-renderer';
import {layoutFlow,flowLabelLines} from '../src/taskFlowLayout.js';
const fixture={id:'main.py::<module>',file:'main.py',line:1,title:'入口流程',summary:'',nodes:[
  {id:'end',kind:'end',label:'结束',calls:[],line:9,file:'main.py'},
  {id:'start',kind:'start',label:'开始',calls:[],line:1,file:'main.py'},
  {id:'if',kind:'decision',label:'判断条件',calls:[],line:2,file:'main.py'},
  {id:'yes',kind:'call',label:'调用 helper',calls:[{name:'helper',target:'helper.py::work'}],line:3,file:'main.py'},
  {id:'no',kind:'log',label:'输出日志',calls:[],line:5,file:'main.py'}],
  edges:[{from:'start',to:'if',kind:'normal',label:''},{from:'if',to:'yes',kind:'normal',label:'是'},
    {from:'if',to:'no',kind:'normal',label:'否'},{from:'yes',to:'end',kind:'normal',label:''},
    {from:'no',to:'if',kind:'loop',label:'继续'}]};
const layout=layoutFlow(fixture),positions=new Map(layout.nodes.map(node=>[node.id,node]));
assert.ok(positions.get('start').y<positions.get('if').y);
assert.equal(positions.get('yes').y,positions.get('no').y);
assert.notEqual(positions.get('yes').x,positions.get('no').x);
assert.ok(positions.get('end').y>positions.get('yes').y);
assert.ok(layout.edges.every(edge=>!edge.path.includes('NaN')));
assert.ok(layout.nodes.every(node=>node.x>116 && node.x+116<layout.width));
assert.equal(flowLabelLines('中文'.repeat(60)).length,3);
assert.ok(flowLabelLines('中文'.repeat(60))[2].endsWith('…'));
const componentPath=new URL(`.task-flow-viewer-${process.pid}.mjs`,import.meta.url);
const mockPath=new URL(`.task-flow-api-${process.pid}.mjs`,import.meta.url);
const {descriptor}=parse(await readFile(new URL('../src/components/TaskFlowViewer.vue',import.meta.url),'utf8'));
await writeFile(mockPath,`export const requests=[]; export const api={
  taskFlow:pid=>new Promise((resolve,reject)=>requests.push({pid,resolve,reject})),
  taskSources:async()=>({entries:[],has_more:false,truncated:false,next_offset:0}),
  taskSource:async(pid,path)=>({path,kind:'text',content:Array.from({length:450},(_,i)=>'line '+(i+1)).join('\\n'),sha256:'current'})
};`);
const compile=inlineTemplate=>compileScript(descriptor,{id:'flow-regression',inlineTemplate}).content
  .replace("'../api'",JSON.stringify(mockPath.href)).replace("'../taskFlowLayout'","'../src/taskFlowLayout.js'")
  .replace("import LoadingStatus from './LoadingStatus.vue';",'const LoadingStatus = {render:()=>null};');
await writeFile(componentPath,compile(false));
try{
  const {default:Component}=await import(componentPath.href);const {requests}=await import(mockPath.href);
  let state;const events=[];
  await renderToString(createSSRApp({setup(){state=Component.setup({pid:'first',revision:0},{expose(){},emit:(...args)=>events.push(args)});return()=>null;}}));
  const second=state.load();
  const payload={graphs:[fixture],files:[{path:'main.py',sha256:'analysis'}],entry:'main.py',fingerprint:'proof',warnings:[],limitations:[],code_version:''};
  requests[1].resolve(payload);await second;
  requests[0].reject(new Error('stale failure'));await Promise.resolve();await Promise.resolve();
  assert.equal(state.error.value,'');assert.deepEqual(state.data.value,payload);
  const helper={...fixture,id:'helper.py::work',title:'work',summary:'处理数据'};
  state.data.value={...payload,graphs:[fixture,helper]};state.graphId.value=fixture.id;
  state.expand(helper.id);assert.equal(state.graphId.value,helper.id);state.back();assert.equal(state.graphId.value,fixture.id);
  state.selectedId.value='yes';state.showSource();
  assert.deepEqual(events.at(-1),['source',{file:'main.py',line:3,sha256:'analysis'}]);
  const sourcePath=new URL(`.task-flow-source-${process.pid}.mjs`,import.meta.url);
  const sourceDescriptor=parse(await readFile(new URL('../src/components/TaskSourceViewer.vue',import.meta.url),'utf8')).descriptor;
  await writeFile(sourcePath,compileScript(sourceDescriptor,{id:'flow-source-regression',inlineTemplate:false}).content
    .replace("'../api'",JSON.stringify(mockPath.href)).replace("import LoadingStatus from './LoadingStatus.vue';",'const LoadingStatus = {render:()=>null};'));
  try {
    const SourceComponent=(await import(sourcePath.href)).default;let sourceState;
    await renderToString(createSSRApp({setup(){sourceState=SourceComponent.setup({pid:'first',location:null},{expose(){},emit(){}});return()=>null;}}));
    await Promise.resolve();
    await sourceState.openFile('main.py',220,'current');
    assert.equal(sourceState.focusedLine.value,220);assert.equal(sourceState.page.value,2);assert.equal(sourceState.versionNotice.value,'');
    await sourceState.openFile('main.py',220,'analysis');
    assert.equal(sourceState.focusedLine.value,0);assert.match(sourceState.versionNotice.value,/代码已更新/);
  } finally {await unlink(sourcePath);}
  console.log('Task flow branch layout, loop routes, function navigation and stale failures passed.');
}finally{await Promise.all([unlink(componentPath),unlink(mockPath)]);}
