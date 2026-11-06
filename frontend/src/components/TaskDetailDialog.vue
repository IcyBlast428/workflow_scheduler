<template>
  <ModalShell :open="Boolean(pid)" :label="`任务详情：${data.task_name || pid}`" panel-class="task-detail-modal task-workbench" backdrop-class="task-workbench-backdrop" @close="close">
      <header class="modal-head"><h3>任务详情：{{ data.task_name || pid }}</h3><button class="btn icon-only" title="关闭" aria-label="关闭" @click="close">×</button></header>
      <div class="modal-body task-detail-body">
        <section v-if="data.pid" class="workbench-summary" aria-label="任务运行摘要">
          <div><small>调度状态</small><strong>{{ scheduleStatus }}</strong></div>
          <div><small>最近结果</small><strong><span v-if="latestCompleted" class="tag" :class="statusClass(latestCompleted.status)">{{ statusLabel(latestCompleted.status) }}</span><template v-else>暂无记录</template></strong></div>
          <div><small>下次执行</small><strong>{{ displayDateTime(data.diagnostics?.next_run_time, '未安排') }}</strong></div>
          <div><small>当前代码版本</small><strong class="mono" :title="data.current_version">{{ data.current_version?.slice(0,12) || '未记录' }}</strong></div>
        </section>
        <div v-if="taskIssue" class="inline-alert warning"><strong>{{ taskIssue }}</strong><div class="filter-actions"><button v-if="latestCompleted && ['failed','timed_out','interrupted','skipped','missed'].includes(latestCompleted.status)" class="btn" @click="selectTab('runs')">查看最近执行</button><button v-if="data.schedule?.application?.status==='failed'" class="btn" @click="selectTab('description')">查看配置生效信息</button></div></div>
        <nav class="workbench-groups" aria-label="任务工作区"><button v-for="group in groups" :key="group.id" class="btn" :class="{primary:activeGroup===group.id}" :disabled="!data.pid || loading" :aria-pressed="activeGroup===group.id" @click="selectTab(group.tabs[0].id)">{{ group.label }}</button></nav>
        <div class="detail-toolbar">
          <div class="filter-actions detail-tabs" role="tablist" aria-label="详情内容"><button v-for="(item,index) in visibleTabs" :key="item.id" :id="`${dialogId}-${item.id}`" role="tab" :aria-controls="`${dialogId}-panel-${item.id}`" :disabled="!data.pid || loading" :aria-selected="tab === item.id" :tabindex="tab === item.id ? 0 : -1" class="btn" :class="tab === item.id ? 'primary' : ''" @keydown="tabKey($event,index)" @click="selectTab(item.id)">{{ item.label }}</button></div>
          <div class="filter-actions detail-actions" aria-label="详情操作">
            <button v-if="permitted('publish')" class="btn" @click="selectTab('releases')">管理代码版本</button>
            <button class="btn" @click="copyLink">{{ linkCopied ? '已复制链接' : '复制当前链接' }}</button>
            <button class="btn detail-refresh" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新详情' }}</button>
          </div>
        </div>
        <p v-if="linkError" class="hint" role="status">{{ linkError }}</p>
        <LoadingStatus :active="loading || (tab === 'source' && sourceLoading) || (tab === 'flow' && flowLoading)" :label="tab === 'source' && sourceLoading ? '正在读取任务文件…' : tab === 'flow' && flowLoading ? '正在分析任务执行流程…' : '正在更新任务详情…'" />
        <div v-if="error" class="inline-alert danger" role="alert">{{ error }}</div>
        <div class="detail-panels" :aria-busy="loading">
        <div v-show="tab === 'description'" role="tabpanel" :id="`${dialogId}-panel-description`" :aria-labelledby="`${dialogId}-description`" tabindex="0" class="detail-tab-panel" aria-label="说明与配置">
          <dl class="task-metadata" aria-label="任务配置信息">
            <div><dt>负责人</dt><dd>{{ data.schedule?.form?.owner || '未填写' }}</dd></div>
            <div><dt>入口文件</dt><dd class="mono">{{ data.schedule?.main_file || '—' }}</dd></div>
            <div><dt>配置版本</dt><dd>{{ data.schedule?.version || 0 }}</dd></div>
            <div><dt>生效状态</dt><dd>{{ ({applied:'已生效',pending:'待生效',failed:'生效失败',unconfigured:'未配置'})[data.schedule?.application?.status] || '待确认' }}</dd></div>
            <div><dt>修改人</dt><dd>{{ data.schedule?.updated_by || '—' }}</dd></div>
            <div><dt>修改时间 · UTC+8</dt><dd :title="data.schedule?.updated_at">{{ displayDateTime(data.schedule?.updated_at) }}</dd></div>
            <div><dt>并发上限</dt><dd>{{ data.schedule?.max_instances ?? '—' }}</dd></div>
            <div><dt>执行超时</dt><dd>{{ data.schedule?.timeout_seconds ? data.schedule.timeout_seconds + ' 秒' : '不限' }}</dd></div>
          </dl>
          <p v-if="data.schedule?.application?.message" class="hint">{{ data.schedule.application.message }}</p>
          <p v-if="data.schedule?.form?.schedule_type === 'once_at' && data.schedule?.preview?.length === 0" class="hint">单次计划时间已过；刷新或重启不会重复执行。可以修改为未来时间重新安排，或手动执行一次。</p>
          <section class="task-description" aria-label="任务说明"><h4>任务说明</h4><MarkdownContent :content="data.schedule?.form?.description || data.description || ''" /></section>
          <h4>最近执行耗时</h4><div class="duration-trend"><span v-for="run in (data.runs || []).slice(0,8)" :key="run.run_id" class="tag" :title="run.created_at">{{ statusLabel(run.status) }} · {{ duration(run) }}</span></div>
          <h4>调度诊断</h4><p>全局活动实例 {{ data.diagnostics?.active }} / {{ data.diagnostics?.capacity }} · 下次计划 {{ displayDateTime(data.diagnostics?.next_run_time, '暂无') }}</p><p v-if="data.diagnostics?.last_not_started">最近未启动：{{ data.diagnostics.last_not_started.reason }} · {{ displayDateTime(data.diagnostics.last_not_started.scheduled_time || data.diagnostics.last_not_started.created_at) }}</p>
          <template v-if="data.notifications?.length"><h4>最近告警</h4><p v-for="alert in data.notifications || []" :key="alert.id">{{ alert.channel === 'sms' ? '短信' : '邮件' }} · {{ {pending:'待发送',sending:'发送中',sent:'网关已接受',unknown:'发送结果待核对',failed:'发送失败',resolved_sent:'人工确认已送达',resolved_not_sent:'人工确认未送达',resolved_manual:'已人工处理'}[alert.status] }} · {{ alert.message }} · {{ displayDateTime(alert.created_at) }}</p></template><p v-else class="hint quiet-notifications">最近无告警</p>
        </div>
        <div v-if="tab === 'schema'" class="detail-tab-panel"><TaskSchema :pid="pid" :editable="permitted('publish')" :confirm="confirm" /></div>
        <div v-show="tab === 'runs'" role="tabpanel" :id="`${dialogId}-panel-runs`" :aria-labelledby="`${dialogId}-runs`" tabindex="0" class="table-wrap detail-tab-panel" aria-label="执行记录"><table><thead><tr><th>执行编号</th><th>状态</th><th>来源 / 操作人</th><th>时间 / 耗时</th><th>操作</th></tr></thead><tbody>
          <tr v-for="run in data.runs || []" :key="run.run_id"><td class="mono">{{ run.run_id.slice(0,12) }}</td><td><span class="tag" :class="statusClass(run.status)">{{ statusLabel(run.status) }}</span><small class="cell-subtitle">{{ run.reason }}</small></td><td>{{ ({manual:'手动',trial:'试运行',retry:'自动重试',backfill:'业务日期补跑'})[run.source] || '自动调度' }} / {{ run.actor }}</td><td :title="run.created_at">{{ displayDateTime(run.created_at) }}<small class="cell-subtitle">{{ duration(run) }}</small></td><td><button class="btn" @click="selectedRun = run.run_id">查看执行</button></td></tr>
        </tbody></table><p v-if="!data.runs?.length" class="hint">还没有新版本的执行记录；旧历史可在执行记录中查看。</p></div>
        <div v-if="tab === 'releases' && permitted('publish')" role="tabpanel" :id="`${dialogId}-panel-releases`" :aria-labelledby="`${dialogId}-releases`"><TaskReleaseDialog embedded :pid="pid" :allow-operations="canManage" :confirm="confirm" @changed="load" @execution="selectedRun=$event;tab='runs'" /></div>
        <div v-if="tab === 'connections' && canManage" role="tabpanel" :id="`${dialogId}-panel-connections`" :aria-labelledby="`${dialogId}-connections`"><TaskConnections :pid="pid" :confirm="confirm" /></div>
        <div v-if="tab === 'operations' && canManage" role="tabpanel" :id="`${dialogId}-panel-operations`" :aria-labelledby="`${dialogId}-operations`"><TaskOperations :pid="pid" :confirm="confirm" @execution="selectedRun=$event;tab='runs'" /></div>
        <div v-if="tab === 'runs' && selectedRun"><ExecutionDialog embedded :run-id="selectedRun" @close="selectedRun = ''" /></div>
        <div v-show="tab === 'versions'" role="tabpanel" :id="`${dialogId}-panel-versions`" :aria-labelledby="`${dialogId}-versions`" tabindex="0" class="table-wrap detail-tab-panel" aria-label="配置历史"><table><thead><tr><th>版本</th><th>修改人</th><th>时间</th><th>操作</th></tr></thead><tbody>
          <tr v-for="item in data.versions || []" :key="item.version"><td>{{ item.version }}</td><td>{{ item.changed_by }}</td><td :title="item.changed_at">{{ displayDateTime(item.changed_at) }}</td><td><button v-if="permitted('schedule')" class="btn" :disabled="restoring" @click="restore(item.version)">恢复此配置</button></td></tr>
        </tbody></table><p class="hint">恢复会生成新版本，不删除历史；沿用该版本的调度启用状态。</p></div>
        <div v-show="tab === 'audit'" role="tabpanel" :id="`${dialogId}-panel-audit`" :aria-labelledby="`${dialogId}-audit`" tabindex="0" class="table-wrap detail-tab-panel" aria-label="操作记录"><table><thead><tr><th>操作人</th><th>操作</th><th>结果</th><th>时间</th></tr></thead><tbody><tr v-for="(item,index) in data.audit || []" :key="index"><td>{{ item.actor }}</td><td>{{ actionLabel(item.action) }}</td><td>{{ item.outcome === 'success' ? '成功' : '失败' }}</td><td :title="item.created_at">{{ displayDateTime(item.created_at) }}</td></tr></tbody></table></div>
        <div v-if="flowVisited" v-show="tab === 'flow'" role="tabpanel" :id="`${dialogId}-panel-flow`" :aria-labelledby="`${dialogId}-flow`" tabindex="0" class="detail-tab-panel"><TaskFlowViewer :key="pid" :pid="pid" :revision="flowRevision" @source="showFlowSource" @loading="flowLoading=$event" /></div>
        <div v-if="sourceVisited" v-show="tab === 'source'" role="tabpanel" :id="`${dialogId}-panel-source`" :aria-labelledby="`${dialogId}-source`" tabindex="0" class="detail-tab-panel"><TaskSourceViewer :key="pid" :pid="pid" :location="sourceLocation" :show-loading-status="false" @loading="sourceLoading = $event" /></div>
        </div>
      </div>
  </ModalShell>
</template>
<script setup>
import MarkdownContent from './MarkdownContent.vue';
import { timestamp, displayDateTime } from '../timebase';
const TaskReleaseDialog = defineAsyncComponent(() => import('./TaskReleaseDialog.vue'));
const TaskOperations = defineAsyncComponent(() => import('./TaskOperations.vue'));
const TaskConnections = defineAsyncComponent(() => import('./TaskConnections.vue'));
import TaskSchema from './TaskSchema.vue';
import ExecutionDialog from './ExecutionDialog.vue';
import ModalShell from './ModalShell.vue';
import { defineAsyncComponent, computed, onMounted, onBeforeUnmount, ref, watch, nextTick, useId } from 'vue';
import { api } from '../api';
import {confirmUnsaved} from '../composables/useUnsavedChanges';
import { statusLabel, actionLabel, statusClass } from '../executionLabels';
import TaskSourceViewer from './TaskSourceViewer.vue';
import TaskFlowViewer from './TaskFlowViewer.vue';
import LoadingStatus from './LoadingStatus.vue';
const props = defineProps({ pid: {type:String,default:''}, canManage:Boolean, confirm:Function });
const emit = defineEmits(['close','execution','confirmRestore','packages']);
const data = ref({}), tab = ref('description'), error = ref(''), loading = ref(false), restoring = ref(false);
const latestCompleted=computed(()=>data.value.runs?.find(run=>!['queued','running'].includes(run.status) && run.source!=='trial'));
const scheduleStatus=computed(()=>data.value.configuration_error?'配置异常':data.value.schedule?.application?.status==='failed'?'生效失败':data.value.schedule?.application?.status==='pending'?'待生效':!data.value.schedule?.configured?'未配置':data.value.schedule.enabled?'已启用':'已暂停');
const taskIssue=computed(()=>data.value.configuration_error || (data.value.schedule?.application?.status==='failed' && (data.value.schedule.application.message || '调度配置未生效')) || (['failed','timed_out','interrupted','skipped','missed'].includes(latestCompleted.value?.status) ? latestCompleted.value.reason || statusLabel(latestCompleted.value.status) : '') || '');
const selectedRun = ref('');
const sourceVisited = ref(false);
const sourceLoading = ref(false);
const flowVisited=ref(false),flowRevision=ref(0),flowLoading=ref(false),sourceLocation=ref(null);
async function close(){if(await confirmUnsaved(props.confirm))emit('close');}
async function selectTab(id) { if(id!==tab.value && !await confirmUnsaved(props.confirm))return; if (id === 'source') sourceVisited.value = true; if(id === 'flow')flowVisited.value=true; tab.value = id; }
function showFlowSource(location) { sourceLocation.value={...location,key:Date.now()};sourceVisited.value=true;tab.value='source'; }
const permitted = capability => props.canManage || data.value.permissions?.includes(capability);
const tabs = computed(() => [{id:'description',label:'说明与配置'},{id:'schema',label:'DDL 与标签'},{id:'flow',label:'执行流程'},{id:'source',label:'查看代码'},{id:'runs',label:props.canManage ? '执行与输出' : '执行记录'},{id:'releases',label:'代码版本'},{id:'connections',label:'连接授权'},{id:'operations',label:'运行策略'},{id:'versions',label:'配置历史'},{id:'audit',label:'操作记录'}].filter(item => props.canManage || ['description','runs'].includes(item.id) || ['source','flow'].includes(item.id) && permitted('view_code') || item.id==='schema' && (permitted('view_code') || permitted('publish')) || item.id==='releases' && permitted('publish') || item.id==='versions' && permitted('schedule')));
const groupDefinitions=[{id:'overview',label:'概览',ids:['description','flow']},{id:'execution',label:'执行',ids:['runs']},{id:'configuration',label:'配置',ids:['operations','versions']},{id:'publication',label:'发布',ids:['releases','source','schema']},{id:'security',label:'安全与审计',ids:['connections','audit']}];
const groups=computed(()=>groupDefinitions.map(group=>({...group,tabs:group.ids.map(id=>tabs.value.find(item=>item.id===id)).filter(Boolean)})).filter(group=>group.tabs.length));
const activeGroup=computed(()=>groups.value.find(group=>group.ids.includes(tab.value))?.id || 'overview');
const visibleTabs=computed(()=>groups.value.find(group=>group.id===activeGroup.value)?.tabs || []);
const linkCopied=ref(false),linkError=ref('');
let restoringLocation=false;
function locationParams(){return new URLSearchParams(window.location.hash.split('?')[1] || '');}
function writeLocation(replace=false){
  if(!props.pid || !data.value.pid || restoringLocation)return;
  const params=locationParams();if(params.get('pid')!==props.pid)return;
  params.set('detail',tab.value);
  if(tab.value==='runs' && selectedRun.value)params.set('detailRun',selectedRun.value);else params.delete('detailRun');
  const hash=window.location.hash.split('?')[0]+'?'+params.toString();
  if(hash!==window.location.hash)window.history[replace?'replaceState':'pushState'](null,'',hash);
}
async function restoreLocation(){
  if(!props.pid || !data.value.pid || locationParams().get('pid')!==props.pid)return;
  const params=locationParams(),wanted=params.get('detail') || 'description';
  const next=tabs.value.some(item=>item.id===wanted)?wanted:'description';
  const run=next==='runs' && /^[a-f0-9]{32}$/i.test(params.get('detailRun') || '')?params.get('detailRun'):'';
  if((next!==tab.value || run!==selectedRun.value) && !await confirmUnsaved(props.confirm)){writeLocation(true);return;}
  restoringLocation=true;
  tab.value=next;selectedRun.value=run;
  if(next==='source')sourceVisited.value=true;if(next==='flow')flowVisited.value=true;
  await nextTick();restoringLocation=false;
}
async function copyLink(){writeLocation(true);try{await navigator.clipboard.writeText(window.location.href);linkCopied.value=true;linkError.value='';}catch{linkError.value='无法访问剪贴板，请复制浏览器地址栏中的当前链接。';}}
watch([tab,selectedRun],()=>{linkCopied.value=false;writeLocation();},{flush:'post'});
onMounted(()=>window.addEventListener('hashchange',restoreLocation));
const dialogId = useId();
watch(() => props.canManage, value => { if (!value) { tab.value = 'description'; sourceVisited.value = false; flowVisited.value = false; sourceLocation.value = null; } });
async function tabKey(event,index) {
  if (!['ArrowRight','ArrowLeft','Home','End'].includes(event.key)) return;
  event.preventDefault();
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? visibleTabs.value.length-1 : (index+(event.key === 'ArrowRight' ? 1 : -1)+visibleTabs.value.length)%visibleTabs.value.length;
  await selectTab(visibleTabs.value[next].id); if(tab.value!==visibleTabs.value[next].id)return; await nextTick(); document.getElementById(`${dialogId}-${visibleTabs.value[next].id}`)?.focus();
}
let generation = 0;
async function load() {
  if (!props.pid) return;
  const seq = ++generation; loading.value = true;
  try { const result = await api.taskDetail(props.pid); if (seq === generation) { data.value = result; error.value = ''; if(flowVisited.value)flowRevision.value++; await restoreLocation(); } }
  catch (err) { if (seq === generation) error.value = err.message; }
  finally { if (seq === generation) loading.value = false; }
}
function duration(run) {
  if (!run.start_time || !run.end_time) return '尚未结束';
  return `${Math.max(0,(timestamp(run.end_time) - timestamp(run.start_time)) / 1000).toFixed(1)} 秒`;
}
function restore(version) { emit('confirmRestore', {pid:props.pid, restore_version:version, version:data.value.schedule.version, done:load}); }
watch(() => props.pid, () => { generation++; selectedRun.value=''; tab.value = 'description'; sourceVisited.value = false; sourceLoading.value = false; flowVisited.value=false;flowRevision.value=0;flowLoading.value=false;sourceLocation.value=null;data.value = {}; linkCopied.value=false;linkError.value=''; error.value = ''; loading.value = false; load(); }, {immediate:true});
onBeforeUnmount(() => {generation++;window.removeEventListener('hashchange',restoreLocation);});
</script>

<style>
.modal-backdrop.task-workbench-backdrop{display:flex;align-items:stretch;justify-content:flex-end;padding:12px}.task-detail-modal.task-workbench{width:min(1320px,100%);height:calc(100dvh - 24px);max-height:calc(100dvh - 24px);margin-left:auto}.workbench-groups{display:flex;gap:8px;flex-wrap:wrap;padding:12px 0;border-bottom:1px solid var(--line);flex:none}.workbench-groups .btn{min-height:38px}.task-workbench .detail-tabs{flex:1 1 240px}.task-workbench .detail-tabs .btn.primary{background:var(--brand-soft);color:var(--brand);border-color:var(--brand)}.task-workbench .detail-toolbar{padding-top:12px}.task-workbench .detail-panels{overflow:auto}.task-workbench .workbench-summary{gap:12px}.task-workbench .detail-tab-panel{min-height:200px;height:auto}.task-workbench .detail-tab-panel:has(.source-viewer){height:100%}
@media(max-width:600px){.modal-backdrop.task-workbench-backdrop{padding:0}.task-detail-modal.task-workbench{height:100dvh;max-height:100dvh;border-radius:0}.task-workbench .modal-body{padding:12px}.task-workbench .workbench-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.task-workbench .detail-toolbar .btn{min-height:34px;padding:6px 10px}.task-workbench .loading-status{height:24px;padding:0}.workbench-groups{gap:4px}.workbench-groups .btn{padding:6px 10px}}
</style>

<style scoped>
.task-metadata{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px 24px;margin:4px 0 20px;padding-bottom:20px;border-bottom:1px solid var(--line)}
.task-metadata>div{min-width:0}.task-metadata dt{font-size:12px;color:var(--muted);margin-bottom:6px}.task-metadata dd{margin:0;font-size:14px;line-height:1.6;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.task-description{padding:0 0 20px;border-bottom:1px solid var(--line)}.task-description>h4{font-size:13px;color:var(--muted);margin:0 0 12px}.quiet-notifications{font-size:12px;padding-top:12px;border-top:1px solid var(--line)}
@media(max-width:1100px){.task-metadata{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:480px){.task-metadata{gap:14px 16px}.task-metadata dd{font-size:13px}}
</style>
