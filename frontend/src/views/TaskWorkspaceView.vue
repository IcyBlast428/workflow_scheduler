<template>
  <div class="summary-grid">
    <div class="metric-card">
      <span>任务总数</span>
      <strong>{{ tasks.total }}</strong>
    </div>
    <div class="metric-card">
      <span>本页调度已启用</span>
      <strong>{{ taskSummary.running }}</strong>
    </div>
    <div class="metric-card">
      <span>本页有活动实例</span>
      <strong>{{ taskSummary.pending }}</strong>
    </div>
    <div class="metric-card">
      <span>本页配置异常</span>
      <strong>{{ taskSummary.invalid }}</strong>
    </div>
    <div class="metric-card">
      <span>本页连续失败合计</span>
      <strong>{{ taskSummary.failed }}</strong>
    </div>
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
          class="btn primary"
          type="button"
          @click="$emit('packages')"
        >
          任务示例
        </button>
      </div>
    </div>
    <GitlabTaskChanges v-if="canManage" :first-page="tasks.params.currentPage === 1" @state="gitlabChanges = $event.items" @open="$emit('release', $event)" @settings="$emit('gitlab')" />
    <form class="filter-grid" @submit.prevent="$emit('search')">
      <div class="form-row">
        <label for="taskid">任务 ID</label>
        <input
          id="taskid"
          v-model.trim="tasks.params.taskid"
          class="input"
          placeholder="PID"
        />
      </div>
      <div class="form-row">
        <label for="taskname">任务名称</label>
        <input
          id="taskname"
          v-model.trim="tasks.params.taskname"
          class="input"
          placeholder="名称关键字"
        />
      </div>
      <div class="form-row">
        <label for="taskgroup">任务分组</label>
        <select id="taskgroup" v-model="tasks.params.taskgroup" class="select">
          <option value="">全部分组</option>
          <option v-for="group in tasks.groups" :key="group" :value="group">
            {{ group }}
          </option>
        </select>
      </div>
      <div class="form-row">
        <label for="task-status">任务状态</label
        ><select id="task-status" v-model="tasks.params.status" class="select">
          <option value="">全部状态</option>
          <option value="active">有活动实例</option>
          <option value="failed">最近结果异常</option>
          <option value="invalid">配置异常</option>
          <option value="enabled">调度已启用</option>
        </select>
      </div>
      <div class="form-row">
        <label for="task-owner">负责人</label
        ><input
          id="task-owner"
          v-model.trim="tasks.params.owner"
          class="input"
          placeholder="负责人关键字"
        />
      </div>
      <div class="filter-actions">
        <button class="btn primary" type="submit">
          <span class="btn-icon">?</span>
          搜索
        </button>
        <button class="btn" type="button" @click="$emit('reset')">清空</button>
        <label class="checkbox-row"
          ><input
            :checked="onlyFavorites"
            type="checkbox"
            @change="$emit('favorites-only', $event.target.checked)"
          />仅看收藏</label
        >
      </div>
    </form>
    <div v-if="canOperate" class="batch-toolbar">
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
    <LoadingStatus :active="tasks.loading" label="正在更新任务列表…" />
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
