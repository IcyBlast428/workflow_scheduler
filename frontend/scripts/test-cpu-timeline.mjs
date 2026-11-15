import assert from 'node:assert/strict';
import {createRenderer,ref,computed,nextTick,h} from 'vue';
import {normalizeSamples,normalizeTasks,timelineRange,layoutTaskLanes,MAX_TASK_LANES,formatTick,formatDuration} from '../src/cpuTimelineData.js';
import {useCpuTimelineViewport} from '../src/composables/useCpuTimelineViewport.js';

const end=Date.parse('2030-01-01T04:00:00Z');
const samples=normalizeSamples([
  {time:'2030-01-01 12:00:00',cpu:120,memory:-1},
  {time:'invalid',cpu:50},
  {time:'2030-01-01 11:00:00',cpu:25},
]);
assert.equal(samples.length,2);
assert.equal(samples[1].time,end,'Naive timestamps use the business timezone');
assert.deepEqual(samples.map(s=>[s.cpu,s.memory]),[[25,null],[100,0]]);
assert.equal(formatTick(end,3600000),'12:00');
assert.equal(formatDuration(end-61000,end),'1 分 1 秒');
const markers=[
  {id:'task-a',name:'运行名称',start_time:'2030-01-01 11:00:00',source:'memory'},
  {id:'task-a',name:'完成名称',start_time:'2030-01-01 11:00:01',end_time:'2030-01-01 11:10:00',state:1,source:'history'},
  {id:'task-b',start_time:'2030-01-01 11:30:00'},
  {id:'invalid',start_time:'invalid'},
];
const original=structuredClone(markers),tasks=normalizeTasks(markers,end);
assert.deepEqual(markers,original,'Normalization must never mutate interface data');
assert.equal(tasks.length,2);
assert.equal(tasks[0].running,false);assert.equal(tasks[0].failed,true);
assert.equal(tasks[0].label,'task-a · 完成名称');
assert.equal(tasks[1].running,true);assert.equal(tasks[1].end,end);
assert.equal(timelineRange([{time:end-24*3600000}],[],6,end).start,end-6*3600000);
assert.equal(timelineRange([],[],6,end).end-timelineRange([],[],6,end).start,300000);
const overlapping=Array.from({length:100},(_,id)=>({id,start:end-60000,end}));
const lanes=layoutTaskLanes(overlapping,3600000,800);
assert.equal(Math.max(...lanes.map(task=>task.lane)),MAX_TASK_LANES-1);
assert.equal(lanes.length,100,'Overflow uses bounded lanes without dropping task markers');

// Mount the composable in a real Vue lifecycle so listener cleanup is exercised.
const previousWindow=globalThis.window;
const listeners=new Map();
globalThis.window={
  addEventListener(type,callback){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(callback);},
  removeEventListener(type,callback){listeners.get(type)?.delete(callback);},
};
const renderer=createRenderer({
  createElement:type=>({type,children:[]}),createText:text=>({text}),createComment:()=>({}),
  insert(child,parent){parent.children.push(child);child.parent=parent;},
  remove(child){child.parent.children=child.parent.children.filter(node=>node!==child);},
  setElementText(node,text){node.text=text;},setText(node,text){node.text=text;},
  parentNode:node=>node.parent,nextSibling:()=>null,patchProp(){},
});
let viewport;
const range=ref({start:end-6*3600000,end}),hasData=ref(true);
const app=renderer.createApp({setup(){
  viewport=useCpuTimelineViewport({chartRoot:ref({getBoundingClientRect:()=>({left:20,top:30})}),fullRange:range,
    plotLeft:56,plotRight:computed(()=>856),plotWidth:computed(()=>800),hasData});
  return()=>h('div');
}});
const event=(properties={})=>({clientX:860,clientY:100,preventDefault(){this.prevented=true;},...properties});
const dispatch=(type,value)=>{for(const callback of listeners.get(type) || [])callback(value);};
try {
  app.mount({children:[]});
  assert.equal(viewport.viewStart.value,range.value.start);assert.equal(viewport.viewEnd.value,end);
  assert.equal(viewport.timeForX(856),end);
  viewport.handleWheel(event({deltaY:-1}));
  assert.equal(viewport.viewEnd.value,end,'Right edge zoom keeps the latest time anchored');
  const span=viewport.viewEnd.value-viewport.viewStart.value;
  assert.equal(span,6*3600000*.8);
  range.value={...range.value,end:end+5000};await nextTick();
  assert.equal(viewport.viewEnd.value,end+5000,'Live view follows new samples without resetting zoom');
  assert.equal(viewport.viewEnd.value-viewport.viewStart.value,span);
  viewport.handleMouseDown(event({button:1,clientX:400}));dispatch('mousemove',event({clientX:500}));
  assert.equal(viewport.dragging.value,true);
  dispatch('mouseup',event());assert.equal(viewport.dragging.value,false);
  assert.equal(listeners.get('mousemove').size,0);
  const historical=[viewport.viewStart.value,viewport.viewEnd.value];
  range.value={...range.value,end:end+10000};await nextTick();
  assert.deepEqual([viewport.viewStart.value,viewport.viewEnd.value],historical,'Reviewing older samples must not jump on refresh');
  for(let i=0;i<50;i++)viewport.handleWheel(event({deltaY:-1}));
  assert.equal(viewport.viewEnd.value-viewport.viewStart.value,60000,'Zoom is bounded to one minute');
  for(let i=0;i<100;i++)viewport.handleWheel(event({deltaY:1}));
  assert.equal(viewport.viewStart.value,range.value.start);assert.equal(viewport.viewEnd.value,range.value.end);
  hasData.value=false;
  const emptyWheel=event({deltaY:-1});viewport.handleWheel(emptyWheel);assert.equal(emptyWheel.prevented,undefined);
  viewport.handleMouseDown(event({button:1}));app.unmount();
  assert.equal(listeners.get('mousemove').size,0);assert.equal(listeners.get('mouseup').size,0);
  console.log('CPU timeline timezones, marker merging, bounded lanes, zoom, pan, live following and teardown passed.');
} finally {
  if(listeners.get('mousemove')?.size)app.unmount();
  globalThis.window=previousWindow;
}
