<template>
  <LoadingStatus v-if="dashboard.loading" class="dashboard-loading" :active="dashboard.loading" label="正在更新总览…" />
  <div v-if="dashboard.error" class="error-state">{{ dashboard.error }}</div>
  <template v-if="!dashboard.error || dashboard.loaded">
    <RuntimeOverview
      :can-manage="canManage"
      @detail="$emit('detail', $event)"
      @execution="$emit('execution', $event)"
      @admin="$emit('admin')"
      @queue="$emit('queue')"
    />
    <QueueOverview v-if="canManage" @queue="$emit('queue')" />
    <DashboardSummary
      :summary="dashboard.summary"
      :failures="dashboard.failure_rank"
      :recent="dashboard.recent_runs"
      @tasks="$emit('tasks', $event)"
      @detail="$emit('detail', $event)"
    />
    <section class="panel cpu-panel">
      <div class="panel-head cpu-panel-head">
        <div>
          <h2>机器 CPU / 内存与任务运行段</h2>
          <p>
            最近
            {{ dashboard.cpu_timeline.retention_hours || 6 }}
            小时采样，任务运行段叠加在资源曲线上。
          </p>
        </div>
        <div class="cpu-head-actions">
          <span class="tag info">CPU {{ cpuCurrentText }}</span>
          <span class="tag warning">内存 {{ memoryCurrentText }}</span>
          <span v-if="dashboard.cpu_timeline.warning" class="tag warning"
            >采样异常</span
          >
        </div>
      </div>
      <CpuTimelineChart
        :samples="dashboard.cpu_timeline.samples"
        :markers="dashboard.cpu_timeline.markers"
        :retention-hours="dashboard.cpu_timeline.retention_hours || 6"
      />
    </section>
  </template>
</template>
<script setup>
import { computed } from 'vue';
import QueueOverview from '../components/QueueOverview.vue';
import RuntimeOverview from '../components/RuntimeOverview.vue';
import DashboardSummary from '../components/DashboardSummary.vue';
import CpuTimelineChart from '../components/CpuTimelineChart.vue';
import LoadingStatus from '../components/LoadingStatus.vue';
const props = defineProps({
  dashboard: { type: Object, required: true },
  canManage: Boolean,
});
defineEmits(['detail', 'execution', 'admin', 'tasks', 'queue']);
const percent = (value) =>
  value == null || !Number.isFinite(Number(value))
    ? '--'
    : Number(value).toFixed(1) + '%';
const cpuCurrentText = computed(() =>
  percent(props.dashboard.cpu_timeline.current),
);
const memoryCurrentText = computed(() =>
  percent(props.dashboard.cpu_timeline.current_memory),
);
</script>
<style scoped>
.dashboard-loading { position: absolute; top: 0; right: 22px; width: 160px; z-index: 1; pointer-events: none; }
</style>
