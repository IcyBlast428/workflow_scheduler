<template>
  <section class="panel">
  <div class="task-list-heading"><div class="task-summary-strip" aria-label="任务列表摘要">
    <span>匹配任务 <strong>{{ tasks.total }}</strong></span><span>本页启用 <strong>{{ taskSummary.running }}</strong></span><span>本页活动 <strong>{{ taskSummary.pending }}</strong></span><span>本页配置异常 <strong>{{ taskSummary.invalid }}</strong></span><span>本页连续失败 <strong>{{ taskSummary.failed }}</strong></span>
  </div>
    <button v-if="canManage" class="btn" @click="$emit('packages')">任务示例</button></div>
    <div class="task-service-strip"><slot name="maintenance" />
    <GitlabTaskChanges v-if="canManage || canPublish" :can-configure="canManage" :first-page="tasks.params.currentPage === 1" @state="gitlabChanges = $event.items" @open="$emit('release', $event)" @settings="$emit('gitlab')" /></div>
    <form class="task-search" @submit.prevent="$emit('search')">
      <div class="task-search-basic">
        <label>任务名称<input id="taskname" v-model.trim="tasks.params.taskname" class="input" placeholder="搜索名称关键字"></label>
        <label>标签<input v-model.trim="tasks.params.tag" class="input" placeholder="搜索标签"></label>
        <label>任务状态<select v-model="tasks.params.status" class="select" aria-label="任务状态"><option value="">全部状态</option><option value="active">有活动实例</option><option value="failed">最近结果异常</option><option value="invalid">配置异常</option><option value="enabled">调度已启用</option></select></label>
        <div class="filter-actions"><button class="btn primary" type="submit"><svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></svg>搜索</button><button class="btn" type="button" @click="$emit('reset')">清空</button><button class="btn" type="button" :aria-expanded="advancedOpen" aria-controls="task-advanced-filters" @click="advancedOpen=!advancedOpen">更多筛选{{ advancedCount ? ' · '+advancedCount : '' }}</button><label class="checkbox-row"><input :checked="onlyFavorites" type="checkbox" @change="$emit('favorites-only',$event.target.checked)">仅看收藏</label></div>
      </div>
      <div v-show="advancedOpen" id="task-advanced-filters" class="task-search-advanced">
        <label>任务 ID<input id="taskid" v-model.trim="tasks.params.taskid" class="input" placeholder="PID"></label>
        <label>任务分组<select v-model="tasks.params.taskgroup" class="select" aria-label="任务分组"><option value="">全部分组</option><option v-for="group in tasks.groups" :key="group" :value="group">{{ group }}</option></select></label>
        <label>负责人<input v-model.trim="tasks.params.owner" class="input" placeholder="负责人关键字"></label>
      </div>
    </form>
    <div class="list-control-lane"><div v-show="!selectedTasks.length || !canOperate" class="list-view-toolbar"><div class="filter-actions"><label>密度<select v-model="density" class="select" aria-label="任务列表密度"><option value="standard">标准</option><option value="compact">紧凑</option></select></label><details class="column-picker"><summary>显示列</summary><div class="column-options"><label v-for="item in optionalColumns" :key="item.key"><input type="checkbox" v-model="columns" :value="item.key">{{ item.label }}</label></div></details></div><span class="hint">{{ selectedTasks.length ? `已选 ${selectedTasks.length} 项` : '显示偏好自动保存' }}</span></div>
    <div class="batch-lane" :class="{active:selectedTasks.length}"><div v-if="canOperate && selectedTasks.length" class="batch-toolbar">
      <span class="selection-count"
        >已选择 <strong>{{ selectedTasks.length }}</strong> 个任务</span
      >
      <div class="filter-actions">
        <button
          v-if="canOperate"
          class="btn"
          :disabled="!selectedTasks.length || batchBusy"
          @click="$emit('batch', 'pause')"
        >
          批量暂停调度</button
        ><button
          v-if="canOperate"
          class="btn"
          :disabled="!selectedTasks.length || batchBusy"
          @click="$emit('batch', 'start')"
        >
          批量启用调度</button
        ><button
          class="btn"
          :disabled="!selectedTasks.length"
          @click="$emit('clear-selection')"
        >
          取消选择
        </button>
      </div>
    </div>
    </div>
    </div>
    <LoadingStatus class="task-loading" :active="tasks.loading" label="正在更新任务列表…" />
    <div v-if="tasks.error" class="error-state">{{ tasks.error }}</div>
    <div v-if="!tasks.items.length && !tasks.error" class="empty-state">
      <strong>{{ tasks.loading ? '正在读取任务' : '没有匹配的任务' }}</strong>
      <span>{{
        tasks.loading
          ? '正在更新结果，请稍候。'
          : canManage
            ? '可以清空筛选条件；GitLab 新任务会在首页提示发布。'
            : '可以清空筛选条件后重试。'
      }}</span>
    </div>
    <TaskTable
      v-else-if="tasks.items.length"
      :rows="tasks.items" :columns="columns" :density="density"
      :busy="busy || batchBusy"
      :pending-actions="pendingActions"
      :can-operate="canOperate"
      :can-manage="canManage"
      :favorites="favorites"
      :selected="selectedTasks"
      :gitlab-changes="gitlabChanges"
      @release="$emit('release', $event)"
      @favorite="$emit('favorite', $event)"
      @select="$emit('select', $event)"
      @detail="$emit('detail', $event.id)"
      @execution="$emit('execution', $event)"
      @action="(row, state) => $emit('action', row, state)"
      @pause="$emit('pause', $event)"
      @call="$emit('call', $event)"
      @schedule="$emit('schedule', $event)"
      @log="$emit('log', $event)"
    />
    <Pagination
      :page="tasks.params.currentPage"
      :page-size="tasks.params.pagesize"
      :total="tasks.total"
      @page="$emit('page', $event)"
      @page-size="$emit('page-size', $event)"
    />
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue';
import GitlabTaskChanges from '../components/GitlabTaskChanges.vue';
import TaskTable from '../components/TaskTable.vue';
import LoadingStatus from '../components/LoadingStatus.vue';
import Pagination from '../components/Pagination.vue';
const props = defineProps({
  userKey: { type: String, default: '' },
  tasks: { type: Object, required: true },
  selectedTasks: Array,
  favorites: Array,
  onlyFavorites: Boolean,
  batchBusy: Boolean,
  busy: Boolean,
  pendingActions: Object,
  canManage: Boolean,
  canPublish: Boolean,
  canOperate: Boolean,
});
defineEmits([
  'search',
  'reset',
  'page',
  'page-size',
  'batch',
  'clear-selection',
  'packages',
  'release',
  'gitlab',
  'favorite',
  'select',
  'detail',
  'execution',
  'action',
  'pause',
  'call',
  'schedule',
  'log',
  'favorites-only',
]);
const optionalColumns=[{key:'group',label:'组名'},{key:'pending',label:'活动实例 / 上限'},{key:'failed',label:'连续 / 累计失败'}];
const density=ref('standard'),columns=ref([]);
const preferenceKey=computed(()=>`wfs:task-table:v1:${props.userKey}`);
watch(preferenceKey,()=>{let value={};try{value=JSON.parse(localStorage.getItem(preferenceKey.value)||'{}')||{};}catch{}density.value=value.density==='compact'?'compact':'standard';columns.value=Array.isArray(value.columns)?value.columns.filter(key=>optionalColumns.some(item=>item.key===key)):[];},{immediate:true});
watch([density,columns],()=>{try{localStorage.setItem(preferenceKey.value,JSON.stringify({density:density.value,columns:columns.value}));}catch{}},{deep:true});
const gitlabChanges = ref([]);
const advancedOpen=ref(false);
const advancedCount=computed(()=>[props.tasks.params.taskid,props.tasks.params.taskgroup,props.tasks.params.owner].filter(Boolean).length);
const taskSummary = computed(() => ({
  running: props.tasks.items.filter((item) => item.state === 'true').length,
  pending: props.tasks.items.filter((item) => item.pending).length,
  invalid: props.tasks.items.filter((item) => item.state === 'invalid').length,
  failed: props.tasks.items.reduce(
    (sum, item) => sum + Number(item.failed_times || 0),
    0,
  ),
}));
</script>

<style scoped>
.task-loading{height:24px;padding-block:0!important}.task-summary-strip{display:flex;flex-wrap:wrap;gap:12px 24px;padding:8px 20px;color:var(--muted);font-size:13px}.task-summary-strip strong{color:var(--ink);margin-left:6px}.task-search{padding:12px 20px;display:grid;gap:12px}.task-search-basic{display:grid;grid-template-columns:minmax(180px,1fr) minmax(140px,.6fr) auto;gap:12px;align-items:end}.task-search label{display:grid;gap:8px}.task-search .checkbox-row{display:flex;align-items:center}.task-search-advanced{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;padding-top:16px;border-top:1px solid var(--line)}.search-icon{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2}
@media(max-width:1100px){.task-search-basic{grid-template-columns:1fr 1fr}.task-search-basic>.filter-actions{grid-column:1/-1}}
@media(max-width:560px){.panel-head{flex-direction:row;align-items:center;padding:14px}.panel-head p{display:none}.panel-head h2{margin:0}.task-summary-strip{gap:8px 16px;font-size:12px;padding-bottom:12px}.task-search{padding:14px}.task-search-advanced{grid-template-columns:1fr}.task-search-basic{gap:10px;grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
.list-view-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 20px;flex-wrap:wrap}.list-view-toolbar label{white-space:nowrap;display:flex;align-items:center;gap:8px;font-size:13px}.list-view-toolbar .select{min-height:34px;padding-block:6px}.column-picker{position:relative;font-size:13px}.column-picker summary{cursor:pointer;padding:8px}.column-options{position:absolute;z-index:5;top:100%;left:0;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;min-width:200px;box-shadow:var(--shadow);display:grid;gap:12px}.list-control-lane{min-height:56px;position:sticky;top:0;z-index:4;background:var(--panel)}.batch-lane{min-height:0}.batch-lane.active{background:var(--panel);box-shadow:0 3px 12px #0004}.batch-toolbar{padding:8px 20px;border-bottom:0}.task-search-basic>.filter-actions{grid-column:1/-1}
@media(min-width:1300px){.task-search-basic{grid-template-columns:minmax(180px,1fr) minmax(130px,.6fr) 140px auto}.task-search-basic>.filter-actions{grid-column:auto;align-self:end;min-height:40px}.task-search-basic>.filter-actions .btn{padding-inline:10px}.task-search-basic>.filter-actions{gap:6px}}
.panel-head{padding-block:14px}.task-loading{height:20px}
@media(max-width:600px){.list-control-lane{min-height:112px}.batch-toolbar{gap:8px;align-items:center}.batch-toolbar .btn{min-height:34px;padding:6px 8px;font-size:12px}.batch-toolbar .filter-actions{gap:6px}.list-view-toolbar>.hint{font-size:12px}}
</style>

<style scoped>
.task-list-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 20px;border-bottom:1px solid var(--line)}
.task-list-heading .task-summary-strip{padding:0;gap:8px 20px}.task-list-heading>.btn{flex:none;font-size:13px;min-height:34px}
.task-service-strip{display:flex;flex-wrap:wrap;align-items:flex-start;border-bottom:1px solid var(--line);background:var(--panel-soft)}
.task-service-strip>:deep(section){flex:1 1 320px;min-width:0;border-bottom:0;padding:8px 20px}
.task-service-strip>:deep(section:has(.changes-content:not([style*="display: none"]))){flex-basis:100%}
@media(min-width:1300px){.task-search-basic{grid-template-columns:minmax(200px,360px) minmax(140px,240px) 140px auto;justify-content:start}}
@media(max-width:560px){.task-list-heading{padding:12px 14px}.task-list-heading .task-summary-strip{font-size:12px}.task-service-strip>:deep(section){padding-inline:14px}}
</style>
