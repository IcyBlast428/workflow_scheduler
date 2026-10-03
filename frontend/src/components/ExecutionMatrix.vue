<template>
  <section ref="pageElement" class="matrix-page">
    <div class="matrix-toolbar">
      <div><h2>任务执行矩阵</h2><p>分类固定位置 · 高度表示完成时间 · 执行中位于当前平面</p></div>
      <div class="matrix-filters">
        <label class="checkbox-row"><input type="checkbox" v-model="live" @change="changeMode">实时跟随今天</label>
        <label class="matrix-filter-field">日期 <input class="input" type="date" v-model="date" :max="data?.server_time.slice(0,10)" :min="minDate" @change="changeDate"></label>
        <label class="matrix-filter-field">分类 <select class="select" aria-label="分类" v-model="category"><option value="">全部分类</option><option v-for="group in allGroups" :key="group" :value="group">{{ group }}</option></select></label>
        <label class="matrix-filter-field">时间 <select class="select" aria-label="时间" v-model="timeWindow"><option value="day">全天</option><option value="360">最近 6 小时</option><option value="60">最近 1 小时</option></select></label>
        <label class="checkbox-row"><input type="checkbox" v-model="onlyAbnormal">仅看异常</label>
        <button class="btn" @click="toggleFullscreen">全屏 / 退出全屏</button>
        <button class="btn" :disabled="loading" @click="load(true)">{{ loading ? '刷新中…' : '刷新' }}</button>
      </div>
    </div>
    <LoadingStatus :active="loading" label="正在更新执行矩阵…" />
    <div v-if="error" class="matrix-notice" role="alert">{{ error }} <button class="btn" :disabled="loading" @click="load(true)">重试</button></div>
    <template v-if="data">
      <div class="matrix-summary">
        <span><strong>{{ visibleData.tasks.length }}</strong> 个任务 / {{ groups.length }} 个类别</span>
        <span><strong>{{ data.total_executions.toLocaleString() }}</strong> 次调度记录</span>
        <span><strong>{{ data.active.filter(r => r.status === 'running').length }}</strong> 个执行中</span>
        <span>服务器时间 {{ data.server_time }}</span>
        <span>{{ live ? '实时跟随' : '固定历史日期 · 自动刷新已暂停' }} · 当前筛选显示 {{ visibleData.records.length }} 片</span>
      </div>
      <div class="matrix-notice" v-if="data.aggregated">当日记录较多，按 {{ data.bucket_minutes }} 分钟合并为 {{ data.records.length }} 片；同一时间段出现失败即标红。可点击查看次数和原始日志。</div>
      <div class="matrix-notice" v-for="warning in data.warnings" :key="warning">{{ warning }}</div>
      <div class="matrix-surface">
        <div class="matrix-legend"><span v-for="item in legend" :key="item[0]"><i :class="item[0]"></i>{{ item[1] }}</span></div>
        <canvas ref="canvas" aria-label="任务执行三维视图，可通过下方任务选择框查看任务及执行记录"></canvas>
        <div v-if="!data.tasks.length" class="matrix-empty">还没有可显示的任务</div>
        <div v-else-if="!data.records.length && !data.active.length" class="matrix-empty matrix-empty-small">当天暂无执行记录</div>
        <div class="matrix-surface-note">底层：当日 00:00 · 上方：未来 2 小时内的下一次计划</div>
      </div>
      <div class="matrix-camera-bar"><span>透视视图 · Alt + 左键自由旋转 · Alt + 右键缩放 · Alt + 中键平移 · 单击选中</span><button class="btn" @click="scene?.restore()" @keydown="scene?.keyboard($event)" title="键盘：Alt + 方向键旋转，Alt + 加减号缩放">恢复全景</button></div>
      <div class="matrix-details">
        <section class="matrix-card"><h3>任务定位</h3>
          <label class="matrix-select-label">选择任务<select class="select" v-model="selectedPid" @change="selectedKey = ''"><option value="">选择任务…</option><optgroup v-for="group in groups" :key="group.name" :label="`${group.name} (${group.tasks.length})`"><option v-for="task in group.tasks" :key="task.pid" :value="task.pid">{{ task.name }}</option></optgroup></select></label>
          <template v-if="selectedTask"><p>{{ selectedTask.group }} · 第 {{ position.row }} 行 / 第 {{ position.col }} 列</p><p>{{ selectedTask.pid }}</p><p>{{ selectedTask.invalid ? '配置异常' : !selectedTask.configured ? '尚未配置调度策略' : selectedTask.enabled ? '调度已启用' : '调度未运行' }}</p><button class="btn" @click="$emit('task', selectedPid)">任务详情 / 查看代码</button></template>
          <p v-else>单击方格或选择任务，查看该任务的执行轨迹。</p>
          <label v-if="selectedTask" class="matrix-focus"><input type="checkbox" v-model="focus">突出所选任务</label>
        </section>
        <section class="matrix-card"><h3>所选记录</h3>
          <template v-if="selectedRecord"><p><span class="matrix-status" :class="selectedRecord.status">{{ statusName(selectedRecord.status) }}</span> {{ selectedRecord.time }}</p>
            <template v-if="selectedRecord.count > 1 || data.aggregated && !selectedRecord.run_id && selectedRecord.status !== 'pending'"><p>{{ selectedRecord.start_time }} — {{ selectedRecord.end_time }}</p><p>共 {{ selectedRecord.count }} 次 · 成功 {{ selectedRecord.success || 0 }} · 失败 {{ selectedRecord.failed }}（含超时 {{ selectedRecord.timed_out || 0 }}） · 取消 {{ selectedRecord.cancelled || 0 }} · 中断 {{ selectedRecord.interrupted || 0 }} · 跳过 {{ selectedRecord.skipped || 0 }} · 错过 {{ selectedRecord.missed || 0 }}</p></template>
            <template v-else><p>开始：{{ selectedRecord.start_time }}</p><p v-if="selectedRecord.duration != null">耗时：{{ selectedRecord.duration.toFixed(2) }} 秒</p></template>
            <button v-if="isRun(selectedRecord)" class="btn" @click="$emit('execution', selectedRecord.run_id)">执行详情 / 日志</button>
            <button v-else-if="selectedRecord.end_time" class="btn" @click="$emit('logs', selectedRecord)">查看{{ data.aggregated ? '该时间段' : '原始' }}日志</button>
            <p v-else-if="selectedRecord.status === 'pending'">这是调度器的下一次计划，实际执行时间以调度结果为准。</p>
          </template><p v-else>选择一片执行记录，查看状态和时间。</p>
        </section>
        <section class="matrix-card"><h3>任务执行轨迹 <small v-if="taskRecords.length">{{ taskRecords.length }} 片</small></h3>
          <div class="matrix-record-list" v-if="selectedTask"><button v-for="record in taskRecords.slice(0,recordLimit)" :key="record.key" :class="{ chosen: selectedKey === record.key }" @click="selectedKey = record.key"><i :class="record.status"></i><span>{{ record.time.slice(11,19) }} · {{ statusName(record.status) }}</span><span v-if="record.count > 1">{{ record.count }} 次</span></button><button v-if="taskRecords.length > recordLimit" @click="recordLimit += 200">显示更多记录（已显示 {{ recordLimit }} 片）</button><p v-if="!taskRecords.length">当日暂无执行记录或计划。</p></div><p v-else>选择任务后可按时间浏览，也可通过列表定位被遮挡的方格。</p>
        </section>
      </div>
    </template>
    <div v-else-if="loading" class="matrix-card">正在读取任务与执行记录…</div>
  </section>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { api } from '../api';
import LoadingStatus from './LoadingStatus.vue';
import { createMatrixScene, layoutTasks } from '../executionMatrixScene';
import { statusLabel } from '../executionLabels';
import { readPreference, writePreference, mergeMatrixSnapshot, matrixQuery } from '../workspacePreferences';
const props = defineProps({userKey:{type:String,default:''}});
defineEmits(['task', 'execution', 'logs']);
const canvas=ref(null),data=ref(null),date=ref(''),loading=ref(false),error=ref(''),selectedPid=ref(''),selectedKey=ref(''),focus=ref(false);
const recordLimit=ref(200);
const pageElement=ref(null),live=ref(true),category=ref(''),timeWindow=ref('day'),onlyAbnormal=ref(false);
const preferenceKey=()=>`wfs:matrix:${props.userKey || 'anonymous'}`;
let savedCamera;
function restorePreferences(){const value=readPreference(preferenceKey(),{});category.value=typeof value.category==='string'?value.category:'';timeWindow.value=['day','360','60'].includes(value.timeWindow)?value.timeWindow:'day';onlyAbnormal.value=Boolean(value.onlyAbnormal);savedCamera=value.camera;scene?.setCamera(savedCamera);}
function savePreferences(camera=scene?.getCamera()){writePreference(preferenceKey(),{category:category.value,timeWindow:timeWindow.value,onlyAbnormal:onlyAbnormal.value,camera});}
let scene=null,timer=null,serial=0,disposed=false;
const allGroups=computed(()=>[...new Set((data.value?.tasks || []).map(task=>task.group))]);
const visibleData=computed(()=>{
  if(!data.value)return null;
  const tasks=data.value.tasks.filter(task=>!category.value||task.group===category.value),pids=new Set(tasks.map(task=>task.pid));
  const end=data.value.date===data.value.server_time.slice(0,10)?Date.parse(data.value.server_time.replace(' ','T')):Date.parse(data.value.date+'T23:59:59');
  const filter=record=>pids.has(record.pid)&&(!onlyAbnormal.value||['failed','timed_out','interrupted','skipped','missed','unknown'].includes(record.status))&&(timeWindow.value==='day'||Date.parse(record.time.replace(' ','T'))>=end-Number(timeWindow.value)*60000);
  return {...data.value,tasks,records:data.value.records.filter(filter),active:data.value.active.filter(filter),pending:data.value.pending.filter(filter)};
});
const layout=computed(()=>layoutTasks(visibleData.value?.tasks || [])),groups=computed(()=>layout.value.groups);
const selectedTask=computed(()=>visibleData.value?.tasks.find(t=>t.pid===selectedPid.value));
const position=computed(()=>layout.value.positions.get(selectedPid.value));
const taskRecords=computed(()=>[...(visibleData.value?.records||[]),...(visibleData.value?.active||[]),...(visibleData.value?.pending||[])].filter(r=>r.pid===selectedPid.value).sort((a,b)=>b.time.localeCompare(a.time)));
const selectedRecord=computed(()=>taskRecords.value.find(r=>r.key===selectedKey.value));
const minDate=computed(()=>{if(!data.value)return '';const value=new Date(`${data.value.server_time.slice(0,10)}T12:00:00Z`);value.setUTCDate(value.getUTCDate()-89);return value.toISOString().slice(0,10);});
const legend=['success','running','failed','timed_out','interrupted','skipped','missed','pending','queued','cancelled','unknown'].map(status=>[status,statusLabel(status)]);
const statusName=status=>statusLabel(status);
const isRun=record=>record.inspectable && /^[a-f0-9]{32}$/.test(record.run_id||'');
function updateScene(){scene?.update(visibleData.value,selectedPid.value,focus.value,selectedKey.value);}
async function load(force=false){
  if(disposed||loading.value&&!force)return;
  const current=++serial;loading.value=true;
  try{
    const result=await api.executionMatrix(matrixQuery(live.value,date.value,data.value?.cursor||''));
    if(disposed||current!==serial)return;
    data.value=mergeMatrixSnapshot(data.value,result);date.value=result.date;error.value='';
    if(!result.tasks.some(t=>t.pid===selectedPid.value)){selectedPid.value='';selectedKey.value='';}
    await nextTick();
    if(!scene&&canvas.value)scene=createMatrixScene(canvas.value,record=>{selectedPid.value=record.pid;selectedKey.value=record.key||'';},{camera:savedCamera,onCamera:savePreferences});
    updateScene();
  }catch(exc){if(!disposed&&current===serial)error.value=exc.message||'暂时无法读取执行矩阵。';}
  finally{if(current===serial)loading.value=false;}
}
function refresh(){load(true);}
function changeDate(){live.value=false;load(true);}
function changeMode(){load(true);}
async function toggleFullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else await pageElement.value?.requestFullscreen();}catch{error.value='此浏览器暂不支持全屏，请使用浏览器的全屏功能。';}}
watch([selectedPid,selectedKey,focus],updateScene);
watch([category,timeWindow,onlyAbnormal],()=>{updateScene();savePreferences();});
watch(()=>props.userKey,restorePreferences,{immediate:true});
watch(selectedPid,()=>{recordLimit.value=200;});
onMounted(()=>{load();timer=setInterval(()=>{if(live.value&&!document.hidden)load();},10000);window.addEventListener('wfs:matrix-refresh',refresh);});
onBeforeUnmount(()=>{disposed=true;++serial;clearInterval(timer);window.removeEventListener('wfs:matrix-refresh',refresh);scene?.dispose();});
</script>

<style scoped>
.matrix-page{display:grid;gap:16px}.matrix-toolbar,.matrix-filters,.matrix-summary,.matrix-camera-bar,.matrix-legend{display:flex;align-items:center;gap:16px;flex-wrap:wrap}.matrix-toolbar,.matrix-camera-bar{justify-content:space-between}.matrix-toolbar h2{margin:0;font-size:22px}.matrix-toolbar p,.matrix-card p{color:var(--muted);font-size:13px;line-height:1.65;overflow-wrap:anywhere}.matrix-toolbar p{margin:7px 0 0}.matrix-filters label{display:flex;gap:8px;align-items:center}.matrix-summary{font-size:13px;color:var(--muted)}.matrix-summary strong{color:var(--ink);font-size:19px}.matrix-summary span:last-child{margin-left:auto}.matrix-notice{padding:12px 16px;border:1px solid var(--line);background:var(--panel);border-radius:10px;font-size:13px;color:var(--muted)}.matrix-surface{position:relative;border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--panel);background-image:radial-gradient(var(--line) .7px,transparent .7px);background-size:22px 22px}.matrix-surface canvas{display:block;width:100%;height:clamp(450px,62vh,780px);touch-action:none}.matrix-legend{position:absolute;z-index:1;left:20px;top:16px;font-size:12px;pointer-events:none}.matrix-legend span{display:flex;gap:7px;align-items:center}.matrix-legend i,.matrix-record-list i{display:inline-block;width:10px;height:10px;border-radius:2px;flex-shrink:0}.success{background:#25b778}.running{background:#eabf32}.failed{background:#e45364}.pending{border:1px solid #8393a9;background:transparent}.queued{background:#8a99ac}.cancelled,.unknown{background:#9da9b7}.matrix-surface-note{position:absolute;bottom:13px;left:20px;font-size:11px;color:var(--muted);pointer-events:none}.matrix-camera-bar{font-size:12px;color:var(--muted)}.matrix-details{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.matrix-card{padding:20px;background:var(--panel);border:1px solid var(--line);border-radius:14px;min-width:0}.matrix-card h3{font-size:15px;margin:0 0 14px}.matrix-card small{color:var(--muted);font-weight:normal}.matrix-select-label{display:grid;gap:7px;font-size:12px;color:var(--muted)}.matrix-select-label select{width:100%;min-width:0}.matrix-focus{display:flex;align-items:center;gap:7px;margin-top:14px;font-size:12px}.matrix-record-list{max-height:225px;overflow:auto}.matrix-record-list button{display:flex;gap:9px;align-items:center;justify-content:flex-start;width:100%;padding:10px 7px;background:transparent;border:0;border-bottom:1px solid var(--line);color:var(--ink);text-align:left;cursor:pointer;font-size:12px}.matrix-record-list button.chosen{background:var(--bg);outline:1px solid var(--brand);outline-offset:-1px}.matrix-record-list button span:last-child{margin-left:auto}.matrix-status{padding:3px 8px;border-radius:4px;color:#172a28;font-size:12px}.matrix-empty{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);padding:12px;background:var(--panel);color:var(--muted);pointer-events:none}.matrix-empty-small{top:auto;bottom:40px;transform:translateX(-50%);font-size:12px;white-space:nowrap}@media(max-width:900px){.matrix-details{grid-template-columns:1fr}.matrix-summary span:last-child{margin-left:0}.matrix-surface canvas{height:460px}.matrix-legend{gap:10px;left:12px;top:12px;right:12px}.matrix-surface-note{left:12px;font-size:10px}.matrix-camera-bar{gap:8px}.matrix-camera-bar span{line-height:1.8}}
.unknown{background:#a397c1}
.matrix-toolbar {
  padding: var(--panel-padding);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel-glass);
  gap: 20px;
}
.matrix-toolbar h2 { font-size: 16px; }
.matrix-toolbar > div:first-child { min-width: 0; }
.matrix-filters { gap: 12px 16px; }
.matrix-filter-field { color: var(--muted-strong); font-size: 13px; }
.matrix-filter-field .select { width: auto; min-width: 136px; }
.matrix-filter-field input { width: 164px; }
.matrix-summary, .matrix-camera-bar {
  padding: 16px var(--panel-padding);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel-glass);
}
.matrix-summary { gap: 12px 24px; }
.matrix-surface, .matrix-card, .matrix-notice { border-radius: var(--radius); }
.matrix-card { padding: var(--panel-padding); }
.matrix-legend { background: var(--panel-glass); padding: 10px 12px; border-radius: var(--radius); gap: 8px 14px; }
.matrix-record-list button { padding: 12px; min-height: var(--control-height); border-radius: 4px; }
.matrix-record-list button:hover { background: var(--row-hover); }
.matrix-status { display: inline-flex; align-items: center; min-height: 24px; }
.matrix-status.pending { color: var(--ink); }
@media (max-width: 760px) {
  .matrix-toolbar > div, .matrix-filters { width: 100%; }
  .matrix-filters .matrix-filter-field { display: grid; flex: 1; gap: 6px; min-width: 136px; }
  .matrix-filter-field input, .matrix-filter-field .select { width: 100%; min-width: 0; }
  .matrix-filters > .btn { flex: 1; }
  .matrix-legend { left: 12px; right: 12px; font-size: 11px; }
  .matrix-camera-bar { gap: 12px; }
  .matrix-camera-bar > span { flex: 1 1 240px; }
  .matrix-camera-bar .btn { flex: none; }
}
</style>
