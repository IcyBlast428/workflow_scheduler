<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>执行记录</h2>
        <p>
          默认查看最近 7 天。历史记录可按任务和日期查询，每次日期范围不超过 93
          天。
        </p>
      </div>
    </div>
    <div class="log-shortcuts">
      <span>业务时区：Asia/Shanghai（UTC+8）</span
      ><button
        v-for="range in [
          { days: 1, label: '今天' },
          { days: 7, label: '最近 7 天' },
          { days: 30, label: '最近 30 天' },
        ]"
        :key="range.days"
        class="btn"
        @click="$emit('range', range.days)"
      >
        {{ range.label }}
      </button>
    </div>
    <div v-if="matrixLogRange.length" class="inline-note">
      来自执行矩阵：{{ matrixLogRange[0] }} —
      {{ matrixLogRange[1] }}。搜索或清空可恢复按日期查询。
    </div>
    <form class="filter-grid logs" @submit.prevent="$emit('search')">
      <div class="form-row">
        <label for="task-log-scope">查询范围</label>
        <select
          id="task-log-scope"
          v-model="taskLogs.params.scope"
          class="select"
        >
          <option value="online">近期记录</option>
          <option value="archive">归档记录</option>
          <option value="all">近期与归档</option>
        </select>
      </div>
      <div class="form-row">
        <label for="task-log-id">任务编号</label>
        <input
          id="task-log-id"
          v-model.trim="taskLogs.params.taskid"
          class="input"
          list="task-id-options"
          placeholder="PID"
        />
        <datalist id="task-id-options">
          <option v-for="item in taskLogs.ids" :key="item.id" :value="item.id">
            {{ item.name || item.id }}
          </option>
        </datalist>
      </div>
      <div class="form-row">
        <label for="task-log-name">任务名称</label
        ><input
          id="task-log-name"
          v-model.trim="taskLogs.params.taskname"
          class="input"
          placeholder="名称关键字"
        />
      </div>
      <div class="form-row">
        <label for="task-log-state">执行状态</label>
        <select
          id="task-log-state"
          v-model="taskLogs.params.taskstate"
          class="select"
        >
          <option value="">全部状态</option>
          <option value="成功">成功</option>
          <option value="失败">失败</option>
          <option value="已停止">已停止</option>
          <option value="重启中断">重启中断</option>
          <option value="超时/终止">超时/终止</option>
          <option value="已跳过">已跳过（并发或维护）</option>
          <option value="错过调度">错过调度</option>
        </select>
      </div>
      <div class="form-row">
        <label for="task-log-start">开始日期</label>
        <input
          id="task-log-start"
          v-model="taskLogs.params.startDate"
          class="input"
          type="date"
          required
        />
      </div>
      <div class="form-row">
        <label for="task-log-end">结束日期</label>
        <input
          id="task-log-end"
          v-model="taskLogs.params.endDate"
          class="input"
          type="date"
          required
        />
      </div>
      <div class="filter-actions">
        <button class="btn primary" type="submit">
          搜索
        </button>
        <button class="btn" type="button" @click="$emit('reset')">清空</button>
      </div>
    </form>
    <div v-if="filterChips.length" class="log-filter-chips" aria-label="当前筛选"><span class="hint">当前筛选</span><button v-for="chip in filterChips" :key="chip.key" type="button" class="btn" :aria-label="'清除'+chip.label" @click="$emit('clear-filter',chip.key)">{{ chip.label }}：{{ chip.value }} <span aria-hidden="true">×</span></button></div>
    <LoadingStatus :active="taskLogs.loading" label="正在更新执行记录…" />
    <div class="log-update-lane" aria-live="polite"><button v-if="taskLogs.newRecords" class="btn" :disabled="taskLogs.loading" @click="$emit('updates')">有新执行记录 · 点击查看</button><span v-else class="hint">后台自动检查新结果；阅读、翻页时保留当前列表，避免新记录挤动内容。</span><span v-if="taskLogs.refreshError" class="hint">{{ taskLogs.refreshError }}</span></div>
    <LogTable
      kind="task"
      :rows="taskLogs.rows"
      :loading="taskLogs.loading"
      :error="taskLogs.error"
      :filtered="
        Boolean(
          taskLogs.params.taskid ||
            taskLogs.params.taskname ||
            taskLogs.params.taskstate ||
            matrixLogRange.length,
        )
      "
      @reset="$emit('reset')"
      @tasks="$emit('tasks')"
      @open="$emit('open', $event)"
    />
    <Pagination
      :page="taskLogs.params.currentPage"
      :page-size="taskLogs.params.pagesize"
      :total="taskLogs.total"
      :exact="false"
      :has-more="taskLogs.hasMore"
      :busy="taskLogs.loading"
      @page="$emit('page', $event)"
      @page-size="$emit('page-size', $event)"
    />
  </section>
</template>
<script setup>
import LogTable from '../components/LogTable.vue';
import Pagination from '../components/Pagination.vue';
import LoadingStatus from '../components/LoadingStatus.vue';
import { computed } from 'vue';
import { recentDates } from '../timebase';
const props=defineProps({
  taskLogs: { type: Object, required: true },
  matrixLogRange: Array,
});
const filterChips = computed(() => {
  const params = props.taskLogs.params;
  const defaults = recentDates();
  const matrixRange = props.matrixLogRange?.join(' — ');
  const customDates = !matrixRange && params.startDate && params.endDate && (params.startDate !== defaults.start || params.endDate !== defaults.end);
  return [
    { key:'taskid', label:'任务编号', value:props.taskLogs.ids.find(item => item.id === params.taskid)?.name || params.taskid },
    { key:'taskname', label:'任务名称', value:params.taskname },
    { key:'taskstate', label:'执行状态', value:params.taskstate },
    { key:'scope', label:'查询范围', value:({archive:'归档记录',all:'近期与归档'})[params.scope] },
    { key:'dates', label:'日期范围', value:customDates ? `${params.startDate} — ${params.endDate}` : '' },
    { key:'range', label:'矩阵时间段', value:matrixRange },
  ].filter(item => item.value);
});
defineEmits(['range', 'search', 'reset', 'open', 'page', 'page-size','updates','tasks','clear-filter']);
</script>
<style scoped>.log-update-lane,.log-filter-chips{min-height:48px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:0 var(--panel-padding) 8px}.log-update-lane .hint{font-size:12px}.log-filter-chips .btn{min-height:32px;white-space:normal;overflow-wrap:anywhere}</style>
