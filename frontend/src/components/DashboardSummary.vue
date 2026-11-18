<template>
  <div class="summary-grid dashboard-summary" :aria-busy="!loaded">
    <button v-for="item in cards" :key="item.label" type="button" class="metric-card"
      :disabled="!loaded" @click="$emit('tasks', item.filter)">
      <span>{{ item.label }}</span>
      <strong>{{ loaded ? summary[item.key] ?? 0 : '—' }}</strong>
      <small v-if="loaded">{{ item.filter && !summary[item.key] ? '暂无相关任务' : '查看相关任务 →' }}</small>
    </button>
  </div>
  <section v-if="loaded && failures.length" class="panel dashboard-failures">
    <div class="panel-head">
      <h2>过去 24 小时失败统计</h2>
      <span class="hint">包含执行超时</span>
    </div>
    <div class="dashboard-failure-list">
      <button v-for="item in failures.slice(0, 5)" :key="item.id" type="button"
        class="btn dashboard-failure-row" @click="$emit('detail', item.id)">
        {{ item.name }} <span class="tag danger">{{ item.count }} 次</span>
      </button>
    </div>
  </section>
</template>
<script setup>
defineProps({
  loaded: Boolean,
  summary: { type: Object, default: () => ({}) },
  failures: { type: Array, default: () => [] },
});
defineEmits(['tasks', 'detail']);
const cards = [{label:'任务总数',key:'total',filter:''},{label:'有活动实例',key:'pending',filter:'active'},{label:'最近结果异常',key:'failed_jobs',filter:'failed'},{label:'配置异常',key:'invalid',filter:'invalid'}];
</script>

<style scoped>
.dashboard-summary .metric-card small { color: var(--muted); font-size: 12px; }
.dashboard-summary .metric-card { box-shadow: none; }
.dashboard-summary .metric-card:disabled { cursor: default; }
.dashboard-failures { margin-bottom: 16px; }
.dashboard-failures .panel-head { padding-block: 14px; }
.dashboard-failure-list {
  display: grid;
  gap: 8px;
  padding: 8px var(--panel-padding) 14px;
}
.dashboard-failure-row {
  justify-content: space-between;
  gap: 16px;
  text-align: left;
  white-space: normal;
  overflow-wrap: anywhere;
}
.dashboard-failure-row .tag { flex: none; }
</style>
