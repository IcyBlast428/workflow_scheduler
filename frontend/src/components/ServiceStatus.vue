<template>
  <div class="service-status" role="status" aria-label="服务状态">
    <span
      v-for="item in items"
      :key="item.key"
      class="service-indicator"
      :data-status="item.status"
      :title="`${item.label}：${labels[item.status]} · ${item.message}${status.checkedAt ? ' · ' + status.checkedAt : ''}`"
      :aria-label="`${item.label}：${labels[item.status]}`"
    >
      <i aria-hidden="true" />{{ item.label
      }}<span v-if="item.status !== 'ready'" class="service-result">{{ labels[item.status] }}</span>
    </span>
  </div>
</template>
<script setup>
import { computed } from 'vue';
const props = defineProps({ status: { type: Object, required: true } });
const labels = {
  ready: '正常',
  unavailable: '异常',
  disabled: '未启用',
  unknown: '待检查',
};
const items = computed(() =>
  ['api', 'database', 'scheduler'].map((key) => {
    const component = props.status.components?.[key];
    const status = !props.status.reachable
      ? 'unavailable'
      : key === 'api'
        ? 'ready'
        : component?.status || 'unknown';
    return {
      key,
      label: { api: '接口', database: '数据库', scheduler: '调度器' }[key],
      status,
      message:
        component?.message ||
        (status === 'unavailable' ? '接口连接不可用' : '等待状态检查'),
    };
  }),
);
</script>
<style scoped>
.service-status {
  display: grid;
  gap: 8px;
  font-size: 11px;
  padding: 0 2px 14px;
}
.service-indicator {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--muted-strong);
  white-space: nowrap;
}
.service-indicator i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--muted);
}
.service-indicator[data-status='ready'] i {
  background: var(--success);
}
.service-indicator[data-status='unavailable'] i {
  background: var(--danger);
}
.service-indicator[data-status='unknown'] i {
  background: var(--warning);
}
.service-result {
  font-size: 11px;
  color: var(--muted);
}
.service-indicator[data-status='unavailable'] { color:var(--danger); }
.service-indicator[data-status='unknown'] { color:var(--warning); }
.service-indicator { flex-wrap:wrap; white-space:normal; }
:global(.nav-expanded .sidebar-account .service-status) { grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px 5px; }
:global(.nav-expanded .sidebar-account .service-indicator) { gap:4px; align-content:start; }
@media(max-width:980px){.service-status{display:flex;gap:8px 12px;padding-bottom:8px}}
</style>
