<template>
  <div class="task-summary-strip" aria-label="任务列表摘要">
    <span>匹配任务 <strong>{{ tasks.total }}</strong></span><span>本页启用 <strong>{{ taskSummary.running }}</strong></span><span>本页活动 <strong>{{ taskSummary.pending }}</strong></span><span>本页配置异常 <strong>{{ taskSummary.invalid }}</strong></span><span>本页连续失败 <strong>{{ taskSummary.failed }}</strong></span>
  </div>
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>任务列表</h2>
        <p>
          {{
            canManage
              ? '查看已发布任务，维护调度策略与运行状态。'
              : '查看任务状态、执行计划和执行记录。'
          }}
        </p>
      </div>
      <div class="filter-actions">
        <button
          v-if="canManage"
          class="btn"
          type="button"
          @click="$emit('packages')"
        >
          任务示例
        </button>
      </div>
    </div>
    <GitlabTaskChanges v-if="canManage || canPublish" :can-configure="canManage" :first-page="tasks.params.currentPage === 1" @state="gitlabChanges = $event.items" @open="$emit('release', $event)" @settings="$emit('gitlab')" />
    <form class="task-search" @submit.prevent="$emit('search')">
      <div class="task-search-basic">
        <label>任务名称<input id="taskname" v-model.trim="tasks.params.taskname" class="input" placeholder="搜索名称关键字"></label>
        <label>任务状态<select v-model="tasks.params.status" class="select" aria-label="任务状态"><option value="">全部状态</option><option value="active">有活动实例</option><option value="failed">最近结果异常</option><option value="invalid">配置异常</option><option value="enabled">调度已启用</option></select></label>
        <div class="filter-actions"><button class="btn primary" type="submit"><svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></svg>搜索</button><button class="btn" type="button" @click="$emit('reset')">清空</button><button class="btn" type="button" :aria-expanded="advancedOpen" aria-controls="task-advanced-filters" @click="advancedOpen=!advancedOpen">更多筛选{{ advancedCount ? ' · '+advancedCount : '' }}</button><label class="checkbox-row"><input :checked="onlyFavorites" type="checkbox" @change="$emit('favorites-only',$event.target.checked)">仅看收藏</label></div>
      </div>
      <div v-show="advancedOpen" id="task-advanced-filters" class="task-search-advanced">
        <label>任务 ID<input id="taskid" v-model.trim="tasks.params.taskid" class="input" placeholder="PID"></label>
        <label>任务分组<select v-model="tasks.params.taskgroup" class="select" aria-label="任务分组"><option value="">全部分组</option><option v-for="group in tasks.groups" :key="group" :value="group">{{ group }}</option></select></label>
        <label>负责人<input v-model.trim="tasks.params.owner" class="input" placeholder="负责人关键字"></label>
      </div>
    </form>
    <div v-if="canOperate && selectedTasks.length" class="batch-toolbar">
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
      :rows="tasks.items"
      :busy="busy"
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
import { computed, ref } from 'vue';
import GitlabTaskChanges from '../components/GitlabTaskChanges.vue';
import TaskTable from '../components/TaskTable.vue';
import LoadingStatus from '../components/LoadingStatus.vue';
import Pagination from '../components/Pagination.vue';
const props = defineProps({
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
.task-loading{height:24px;padding-block:0!important}.task-summary-strip{display:flex;flex-wrap:wrap;gap:12px 24px;padding:4px 2px 16px;color:var(--muted);font-size:13px}.task-summary-strip strong{color:var(--ink);margin-left:6px}.task-search{padding:16px 20px;display:grid;gap:16px}.task-search-basic{display:grid;grid-template-columns:minmax(180px,1fr) minmax(140px,.6fr) auto;gap:12px;align-items:end}.task-search label{display:grid;gap:8px}.task-search .checkbox-row{display:flex;align-items:center}.task-search-advanced{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;padding-top:16px;border-top:1px solid var(--line)}.search-icon{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2}
@media(max-width:1100px){.task-search-basic{grid-template-columns:1fr 1fr}.task-search-basic>.filter-actions{grid-column:1/-1}}
@media(max-width:560px){.panel-head{flex-direction:row;align-items:center;padding:14px}.panel-head p{display:none}.panel-head h2{margin:0}.task-summary-strip{gap:8px 16px;font-size:12px;padding-bottom:12px}.task-search{padding:14px}.task-search-advanced{grid-template-columns:1fr}.task-search-basic{gap:10px;grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
</style>
