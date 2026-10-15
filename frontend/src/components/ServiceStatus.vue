<template>
  <div class="service-status" role="status" aria-label="服务状态">
    <span
      v-for="item in items"
      :key="item.key"
      class="service-indicator"
      :data-status="item.status"
      :title="`${item.message}${status.checkedAt ? ' · ' + status.checkedAt : ''}`"
    >
      <i aria-hidden="true" />{{ item.label
      }}<span class="service-result">{{ labels[item.status] }}</span>
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
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 14px;
  font-size: 12px;
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
</style>
