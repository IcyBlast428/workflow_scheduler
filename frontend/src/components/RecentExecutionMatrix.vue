<template>
 <section class="panel recent-executions">
  <div class="panel-head">
   <div><h2>最近 {{ displayedLimit }} 次执行结果</h2><p>每列一个任务，最新结果在最下方，越往上越早。任务名位于方格下方，可横向滚动查看全部任务。</p></div>
   <div class="filter-actions recent-controls">
    <label>执行次数<select v-model.number="limit" class="select"><option v-for="count in limits" :key="count" :value="count">{{ count }} 次</option></select></label>
    <label>分类<select v-model="category" class="select" aria-label="最近执行分类"><option value="">全部分类</option><option v-for="group in allGroups" :key="group" :value="group">{{ group }}</option></select></label>
    <button class="btn" :disabled="loading" @click="load(false)">刷新结果</button>
   </div>
  </div>
  <div class="panel-body recent-body">
   <div class="recent-legend"><span><i class="success" />成功</span><span><i class="failed" />失败 / 超时</span><span><i class="other" />取消 / 中断 / 跳过等</span><span><i class="empty" />无记录</span><small>后台每 5 秒检查 · 查看或操作图表时暂缓替换</small></div>
   <p v-if="error" class="inline-alert danger" role="alert">{{ error }} <button class="btn" @click="load(false)">重试</button></p>
   <p v-if="loading" class="hint" role="status">正在读取每个任务最近 {{ limit }} 次执行结果…</p>
   <div class="recent-update-lane"><button v-if="pending" class="btn" @click="applyPending">有新的执行结果 · 更新图表</button><span v-else class="hint">{{ data ? '点击方块查看状态、结束时间和执行记录。' : '' }}</span></div>
   <div v-if="data" ref="scroll" class="recent-scroll" tabindex="0" :aria-label="`每个任务最近 ${displayedLimit} 次执行结果`" @scroll="rememberScroll" @pointerenter="hovering=true" @pointerleave="hovering=false;flushPending()" @focusin="focused=true" @focusout="focusOut">
    <div class="recent-groups"><div v-if="groups.length" class="recent-ranks" aria-label="最近执行序号"><div class="rank-spacer">序号</div><span v-for="slot in slots" :key="slot">{{ slot }}</span></div>
     <section v-for="group in groups" :key="group.name" class="recent-group"><h3>{{ group.name }} <small>{{ group.tasks.length }} 项</small></h3><div class="recent-columns">
      <div v-for="task in group.tasks" :key="task.pid" class="recent-task">
       <button v-for="slot in slots" :key="slot" class="recent-cell" :class="tone(task.records[slot-1])" :disabled="!task.records[slot-1]" :aria-pressed="Boolean(selected && selected.key===task.records[slot-1]?.key)" :aria-label="describe(task,slot-1)" :title="describe(task,slot-1)" @click="openRecord(task,slot-1)"><span aria-hidden="true">{{ symbol(task.records[slot-1]) }}</span></button>
       <button class="recent-task-name" :title="task.name+' · '+task.pid" :aria-label="'查看任务：'+task.name" @click="$emit('task',task.pid)"><span>{{ task.name }}</span></button>
      </div>
     </div></section>
    </div>
    <p v-if="!groups.length" class="empty-state">暂无可显示的任务。</p>
   </div>
   <p v-if="data" class="hint">每个任务固定展示 {{ displayedLimit }} 格，记录不足时在上方留空。最下方序号 1 为最近一次完成的执行，同一行不代表相同时间。</p>
   <div v-if="selected" class="recent-selection surface-card" aria-live="polite"><div><strong>{{ selected.name }}</strong><p>{{ statusLabel(selected.status) }} · 结束 {{ selected.time }}</p></div><button class="btn" @click="$emit('record',selected)">查看本次详情</button><button class="btn" @click="$emit('history',selected)">查看任务历史</button><button class="btn" @click="selected=null">取消选择</button></div>
  </div>
 </section>
</template>
<script setup>
import {ref,computed,onMounted,onBeforeUnmount,watch,nextTick} from 'vue';
import {api} from '../api';
import {useRefreshLoop} from '../composables/useRefreshLoop.js';
import {statusLabel} from '../executionLabels';
const props=defineProps({active:Boolean});
const emit=defineEmits(['task','record','history']);
const scroll=ref(null);
let scrollLeft=0,scrollTop=0;
function rememberScroll(){if(props.active && scroll.value){scrollLeft=scroll.value.scrollLeft;scrollTop=scroll.value.scrollTop;}}
watch(()=>props.active,async active=>{if(active){await nextTick();scroll.value?.scrollTo(scrollLeft,scrollTop);}else{hovering.value=false;focused.value=false;}});
function openRecord(task,index){if(!task.records[index])return;selected.value={...task.records[index],name:task.name};emit('record',selected.value);}
const data=ref(null),loading=ref(false),error=ref(''),category=ref(''),selected=ref(null),pending=ref(null),hovering=ref(false),focused=ref(false);
const limits=[10,25];
const limit=ref(25);
const displayedLimit=computed(()=>data.value?.limit ?? limit.value);
// The API stays newest-first; only display order is reversed, including empty slots.
const slots=computed(()=>Array.from({length:displayedLimit.value},(_,index)=>displayedLimit.value-index));
let alive=true,inFlight=false,requestId=0,taskSignature='';
const allGroups=computed(()=>[...new Set((data.value?.tasks || []).map(task=>task.group))]);
const groups=computed(()=>{const result=new Map();for(const task of data.value?.tasks || []){if(category.value && task.group!==category.value)continue;if(!result.has(task.group))result.set(task.group,{name:task.group,tasks:[]});result.get(task.group).tasks.push(task);}return [...result.values()];});
const tone=record=>!record?'empty':record.status==='success'?'success':['failed','timed_out'].includes(record.status)?'failed':'other';
const symbol=record=>!record?'':record.status==='success'?'✓':['failed','timed_out'].includes(record.status)?'×':'·';
const describe=(task,index)=>`${task.name} · 最近第 ${index+1} 次 · ${task.records[index]?statusLabel(task.records[index].status)+' · '+task.records[index].time:'无记录'}`;
function applyPending(){if(pending.value){taskSignature=JSON.stringify(pending.value.tasks);data.value=pending.value;pending.value=null;}}
function flushPending(){if(!hovering.value&&!focused.value)applyPending();}
function focusOut(event){if(!event.currentTarget.contains(event.relatedTarget)){focused.value=false;flushPending();}}
async function load(silent=true,replace=false) {
 if(inFlight && !replace)return;
 const id=++requestId;
 inFlight=true;
 if(!silent || !data.value)loading.value=true;
 try {
  const value=await api.recentExecutionMatrix(limit.value);
  if(!alive || id!==requestId)return;
  const changedLimit=value.limit!==data.value?.limit;
  const signature=JSON.stringify(value.tasks);
  const same=!changedLimit && signature===taskSignature;
  pending.value=null;
  error.value='';
  if(same)return;
  if(!changedLimit && silent && (hovering.value || focused.value)){pending.value=value;return;}
  data.value=value;
  taskSignature=signature;
  if(changedLimit){
   await nextTick();
   if(!alive || id!==requestId)return;
   if(scroll.value){scroll.value.scrollTop=scroll.value.scrollHeight;scrollTop=scroll.value.scrollTop;}
   if(selected.value && !value.tasks.find(task=>task.pid===selected.value.pid)?.records.some(record=>record.key===selected.value.key))selected.value=null;
  }
 } catch(e) {
  if(alive && id===requestId)error.value=e.message;
  return false;
 } finally {
  if(alive && id===requestId){inFlight=false;loading.value=false;}
 }
}
watch(limit,()=>{pending.value=null;load(false,true);});
function refresh(event){if(props.active)load(event?.detail?.silent===true);}
useRefreshLoop({load,enabled:()=>props.active});
onMounted(()=>{window.addEventListener('wfs:matrix-refresh',refresh);});onBeforeUnmount(()=>{alive=false;window.removeEventListener('wfs:matrix-refresh',refresh);});
</script>
<style scoped>
.recent-body{display:grid;gap:16px}.recent-legend{display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.recent-legend>span{display:flex;align-items:center;gap:7px}.recent-legend i{width:12px;height:12px;border-radius:3px;border:1px solid var(--line)}.recent-legend small{margin-left:auto}.recent-update-lane{min-height:40px;display:flex;align-items:center}.recent-scroll{overflow:auto;max-height:65dvh;overscroll-behavior:contain;scrollbar-color:var(--brand) var(--panel);padding:12px 12px 6px;border:1px solid var(--line);border-radius:12px;min-width:0}.recent-scroll:focus-visible{outline:2px solid var(--brand);outline-offset:2px}.recent-groups{display:flex;align-items:flex-start;gap:30px;width:max-content;min-width:100%;padding-bottom:6px}.recent-group{flex:none}.recent-group h3{position:sticky;top:0;z-index:3;background:var(--panel);font-size:13px;height:38px;margin:0 0 6px;color:var(--muted-strong);border-bottom:1px solid var(--line);padding-bottom:10px;white-space:nowrap}.recent-group small{font-weight:400;color:var(--muted);font-size:11px}.recent-columns{display:flex;gap:6px}.recent-task{border-radius:6px;align-content:start;display:grid;justify-items:center;gap:6px;width:36px;flex:none}.recent-cell{width:28px;height:28px;display:grid;place-items:center;border:1px solid rgba(255,255,255,.1);border-radius:4px;font-size:13px;color:#fff;cursor:pointer;transition:background-color .18s ease,border-color .18s ease}.success{background:#237b59}.failed{background:#a83f4e}.other{background:#645a47}.empty{background:transparent;border:1px dashed var(--line);cursor:default}.recent-cell:hover:not(:disabled),.recent-cell[aria-pressed=true]{outline:2px solid var(--brand);outline-offset:2px}.recent-cell:focus-visible{outline:2px solid var(--ink);outline-offset:2px}/* Keep vertical names below the results and visible while reviewing older rows. */
.recent-task-name{display:flex;justify-content:center;align-items:flex-start;box-sizing:border-box;height:110px;width:36px;margin:0;position:sticky;bottom:0;z-index:2;padding:8px 4px;border:1px solid transparent;border-radius:6px;background:var(--panel);color:var(--muted-strong);font:inherit;font-family:"Microsoft YaHei UI","Microsoft YaHei","PingFang SC","Noto Sans CJK SC","WenQuanYi Zen Hei Mono",sans-serif;font-size:12px;line-height:20px;cursor:pointer}
.recent-task-name span{display:block;writing-mode:vertical-rl;text-orientation:mixed;max-height:94px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:1px}
.recent-task-name:hover{color:var(--brand);background:var(--panel-soft);border-color:var(--line)}
.recent-task-name:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.recent-controls{flex-wrap:wrap}
.recent-selection{min-height:64px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}.recent-selection p{font-size:12px;color:var(--muted);margin:8px 0 0}.recent-selection>div{margin-right:auto}.recent-executions .filter-actions>label{display:flex;align-items:center;gap:8px;font-size:12px;white-space:nowrap}@media(prefers-reduced-motion:reduce){.recent-cell{transition:none}}
.recent-task:hover,.recent-task:focus-within{background:var(--brand-soft)}.recent-ranks{display:grid;gap:6px;justify-items:center;color:var(--muted);font:12px var(--mono);flex:none;width:30px}.recent-ranks>span{height:28px;display:grid;place-items:center}.rank-spacer{position:sticky;top:0;z-index:3;background:var(--panel);height:38px;padding-top:12px}.recent-body>p.hint{margin:0}
</style>
