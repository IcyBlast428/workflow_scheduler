<template>
 <section class="panel recent-executions">
  <div class="panel-head"><div><h2>最近 10 次执行结果</h2><p>每列一个任务，最新结果在上方 · 分类之间留有间隔 · 可横向滚动</p></div><div class="filter-actions"><label>分类<select v-model="category" class="select" aria-label="最近执行分类"><option value="">全部分类</option><option v-for="group in allGroups" :key="group" :value="group">{{ group }}</option></select></label><button class="btn" :disabled="loading" @click="load(false)">刷新结果</button></div></div>
  <div class="panel-body recent-body">
   <div class="recent-legend"><span><i class="success" />成功</span><span><i class="failed" />失败 / 超时</span><span><i class="other" />取消 / 中断 / 跳过等</span><span><i class="empty" />无记录</span><small>后台每 5 秒检查 · 查看或操作图表时暂缓替换</small></div>
   <p v-if="error" class="inline-alert danger" role="alert">{{ error }} <button class="btn" @click="load(false)">重试</button></p>
   <p v-if="!data && loading" class="hint" role="status">正在读取最近执行结果…</p>
   <div class="recent-update-lane"><button v-if="pending" class="btn" @click="applyPending">有新的执行结果 · 更新图表</button><span v-else class="hint">{{ data ? '点击方块查看状态、结束时间和执行记录。' : '' }}</span></div>
   <div v-if="data" class="recent-scroll" tabindex="0" aria-label="最近10次执行结果，可左右滚动" @pointerenter="hovering=true" @pointerleave="hovering=false;flushPending()" @focusin="focused=true" @focusout="focusOut">
    <div class="recent-groups">
     <section v-for="group in groups" :key="group.name" class="recent-group"><h3>{{ group.name }} <small>{{ group.tasks.length }} 项</small></h3><div class="recent-columns">
      <div v-for="task in group.tasks" :key="task.pid" class="recent-task">
       <button v-for="slot in 10" :key="slot" class="recent-cell" :class="tone(task.records[slot-1])" :disabled="!task.records[slot-1]" :aria-pressed="Boolean(selected && selected.key===task.records[slot-1]?.key)" :aria-label="describe(task,slot-1)" :title="describe(task,slot-1)" @click="selected={...task.records[slot-1],name:task.name}"><span aria-hidden="true">{{ symbol(task.records[slot-1]) }}</span></button>
       <button class="recent-task-name" :title="task.name+' · '+task.pid" @click="$emit('task',task.pid)"><span>{{ task.name }}</span></button>
      </div>
     </div></section>
    </div>
    <p v-if="!groups.length" class="empty-state">暂无可显示的任务。</p>
   </div>
   <div class="recent-selection surface-card" aria-live="polite"><template v-if="selected"><div><strong>{{ selected.name }}</strong><p>{{ statusLabel(selected.status) }} · 结束 {{ selected.time }}</p></div><button class="btn" @click="$emit('logs',selected)">查看执行记录</button><button class="btn" @click="selected=null">取消选择</button></template><span v-else class="hint">选择结果后在这里查看详情。</span></div>
  </div>
 </section>
</template>
<script setup>
import {ref,computed,onMounted,onBeforeUnmount} from 'vue';
import {api} from '../api';
import {statusLabel} from '../executionLabels';
defineEmits(['task','logs']);
const data=ref(null),loading=ref(false),error=ref(''),category=ref(''),selected=ref(null),pending=ref(null),hovering=ref(false),focused=ref(false);
let timer,alive=true,inFlight=false;
const allGroups=computed(()=>[...new Set((data.value?.tasks || []).map(task=>task.group))]);
const groups=computed(()=>{const result=new Map();for(const task of data.value?.tasks || []){if(category.value && task.group!==category.value)continue;if(!result.has(task.group))result.set(task.group,{name:task.group,tasks:[]});result.get(task.group).tasks.push(task);}return [...result.values()];});
const tone=record=>!record?'empty':record.status==='success'?'success':['failed','timed_out'].includes(record.status)?'failed':'other';
const symbol=record=>!record?'':record.status==='success'?'✓':['failed','timed_out'].includes(record.status)?'×':'·';
const describe=(task,index)=>`${task.name} · 最近第 ${index+1} 次 · ${task.records[index]?statusLabel(task.records[index].status)+' · '+task.records[index].time:'无记录'}`;
function applyPending(){if(pending.value){data.value=pending.value;pending.value=null;}}
function flushPending(){if(!hovering.value&&!focused.value)applyPending();}
function focusOut(event){if(!event.currentTarget.contains(event.relatedTarget)){focused.value=false;flushPending();}}
async function load(silent=true){if(inFlight)return;inFlight=true;if(!silent || !data.value)loading.value=true;try{const value=await api.recentExecutionMatrix();if(!alive)return;if(data.value && JSON.stringify(value.tasks)===JSON.stringify(data.value.tasks)){pending.value=null;error.value='';return;}if(silent && data.value && (hovering.value || focused.value)){if(JSON.stringify(value.tasks)!==JSON.stringify(data.value.tasks))pending.value=value;else pending.value=null;}else{data.value=value;pending.value=null;}error.value='';}catch(e){if(alive)error.value=e.message;}finally{inFlight=false;if(alive)loading.value=false;}}
function refresh(event){load(event?.detail?.silent===true);}
onMounted(()=>{load();timer=setInterval(()=>{if(!document.hidden)load();},5000);window.addEventListener('wfs:matrix-refresh',refresh);});onBeforeUnmount(()=>{alive=false;clearInterval(timer);window.removeEventListener('wfs:matrix-refresh',refresh);});
</script>
<style scoped>
.recent-body{display:grid;gap:16px}.recent-legend{display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.recent-legend>span{display:flex;align-items:center;gap:7px}.recent-legend i{width:12px;height:12px;border-radius:3px;border:1px solid var(--line)}.recent-legend small{margin-left:auto}.recent-update-lane{min-height:40px;display:flex;align-items:center}.recent-scroll{overflow-x:auto;overscroll-behavior-x:contain;scrollbar-color:var(--brand) var(--panel);padding:12px 12px 6px;border:1px solid var(--line);border-radius:12px;min-width:0}.recent-scroll:focus-visible{outline:2px solid var(--brand);outline-offset:2px}.recent-groups{display:flex;align-items:flex-start;gap:30px;width:max-content;min-width:100%;padding-bottom:6px}.recent-group{flex:none;content-visibility:auto;contain-intrinsic-size:auto 350px}.recent-group h3{font-size:13px;margin:0 0 16px;color:var(--muted-strong);border-bottom:1px solid var(--line);padding-bottom:10px;white-space:nowrap}.recent-group small{font-weight:400;color:var(--muted);font-size:11px}.recent-columns{display:flex;gap:12px}.recent-task{display:grid;justify-items:center;gap:6px;width:62px;flex:none}.recent-cell{width:28px;height:28px;display:grid;place-items:center;border:1px solid rgba(255,255,255,.1);border-radius:4px;font-size:13px;color:#fff;cursor:pointer;transition:background-color .18s ease,border-color .18s ease}.success{background:#237b59}.failed{background:#a83f4e}.other{background:#645a47}.empty{background:transparent;border:1px dashed var(--line);cursor:default}.recent-cell:hover:not(:disabled),.recent-cell[aria-pressed=true]{outline:2px solid var(--brand);outline-offset:2px}.recent-cell:focus-visible{outline:2px solid var(--ink);outline-offset:2px}.recent-task-name{height:86px;width:62px;position:relative;border:0;background:transparent;color:var(--muted-strong);font:inherit;font-size:11px;text-align:left;cursor:pointer}.recent-task-name span{display:block;width:100px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transform:rotate(-40deg);transform-origin:0 0;position:absolute;top:56px;left:10px}.recent-task-name:hover{color:var(--brand)}.recent-selection{min-height:84px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}.recent-selection p{font-size:12px;color:var(--muted);margin:8px 0 0}.recent-selection>div{margin-right:auto}.recent-executions .filter-actions>label{display:flex;align-items:center;gap:8px;font-size:12px;white-space:nowrap}@media(prefers-reduced-motion:reduce){.recent-cell{transition:none}}
</style>
