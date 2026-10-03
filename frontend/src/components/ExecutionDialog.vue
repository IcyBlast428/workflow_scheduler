<template>
  <div v-if="runId" class="modal-backdrop" @click.self="$emit('close')">
    <section class="modal execution-modal">
      <header class="modal-head"><div><h3>本次执行：{{ record.pid || '加载中' }}</h3><p class="hint mono">{{ runId }}</p></div>
        <button class="btn icon-only" title="关闭" @click="$emit('close')">×</button></header>
      <div class="modal-body">
        <LoadingStatus :active="initialLoading" label="正在读取执行详情与日志…" />
        <div v-if="error" class="inline-alert danger">{{ error }} <button class="btn" @click="refresh">重试</button></div>
        <div class="execution-meta">
          <span class="tag" :class="statusClass(record.status)">{{ statusLabel(record.status) }}</span>
          <span>来源：{{ record.source === 'manual' ? '手动' : '自动调度' }} · {{ record.actor }}</span>
          <span>开始：{{ record.start_time || '尚未开始' }}</span><span>结束：{{ record.end_time || '尚未结束' }}</span>
          <span>最近心跳：{{ record.heartbeat || '-' }}</span>
          <span>计划：{{ record.scheduled_time || record.created_at || '-' }} · 启动延迟：{{ record.start_delay_seconds?.toFixed(2) ?? '-' }} 秒</span>
        </div>
        <details v-if="record.code_version" class="disclosure"><summary>本次执行的代码与环境</summary><div class="disclosure-body"><p>平台版本：{{ record.code_version.release }} · {{ record.code_version.python }}</p><p v-if="record.code_version.task_release" class="mono">任务版本 {{ record.code_version.task_release }} · 包 SHA256 {{ record.code_version.package_sha256 }}</p><p class="mono">入口 {{ record.code_version.entry }} · SHA256 {{ record.code_version.entry_sha256 }}</p><p class="mono">依赖摘要 {{ record.code_version.dependency_sha256 }}</p><p class="hint">代码查看页显示当前文件；历史执行以此处版本和摘要为准。</p></div></details>
        <p v-if="record.reason" class="inline-alert warning">{{ record.reason }}</p>
        <p v-if="record.log_truncated" class="hint">保留日志已达到容量上限，后续输出已丢弃。</p>
        <button v-if="canOperate && record.status && !['queued','running'].includes(record.status)" class="btn" :disabled="retrying" @click="$emit('retry',record)">再执行一次</button>
        <p v-if="displayTruncated" class="hint">页面显示最近 256 KiB；下载可获取容量上限内的保留日志。</p>
        <div class="filter-actions"><input v-model="search" class="input" placeholder="搜索日志内容" aria-label="搜索日志内容">
          <label><input v-model="follow" type="checkbox">自动滚动</label>
          <a class="btn" :href="`/api/taskinfo/run-download?run_id=${runId}`" download>下载保留日志</a></div>
        <pre ref="logElement" class="log-pre execution-output">{{ filtered || '等待任务输出…' }}</pre>
      </div>
    </section>
  </div>
</template>
<script setup>
import { ref, computed, watch, onUnmounted, nextTick } from 'vue';
import { api } from '../api';
import LoadingStatus from './LoadingStatus.vue';
import { statusLabel, statusClass } from '../executionLabels';
const props = defineProps({ runId: { type: String, default: '' }, canOperate:Boolean, retrying:Boolean });
defineEmits(['close','retry']);
const record = ref({}), content = ref(''), error = ref(''), search = ref(''), follow = ref(true), logElement = ref(null), displayTruncated = ref(false);
const initialLoading = ref(false);
let timer, offset = 0, generation = 0, inFlight = false;
const filtered = computed(() => search.value ? content.value.split('\n').filter(line => line.toLowerCase().includes(search.value.toLowerCase())).join('\n') : content.value);
async function refresh() {
  if (!props.runId || inFlight || document.visibilityState === 'hidden') return;
  inFlight = true;
  const seq = generation;
  try {
    const result = await api.execution(props.runId, offset);
    if (seq !== generation) return;
    record.value = result.record;
    content.value += result.content;
    offset = result.next_offset;
    if (content.value.length > 256 * 1024) { content.value = content.value.slice(-256 * 1024); displayTruncated.value = true; }
    error.value = '';
    await nextTick();
    if (follow.value && logElement.value) logElement.value.scrollTop = logElement.value.scrollHeight;
    if (!['queued','running'].includes(record.value.status) && !result.has_more) window.clearInterval(timer);
  } catch (err) { if (seq === generation) error.value = err.message; }
  finally { inFlight = false; if (seq === generation) initialLoading.value = false; }
}
watch(() => props.runId, () => {
  generation++; window.clearInterval(timer); offset = 0; content.value = ''; record.value = {}; error.value = ''; displayTruncated.value = false;
  initialLoading.value = Boolean(props.runId);
  if (props.runId) { timer = window.setInterval(refresh, 1500); refresh(); }
}, { immediate: true });
onUnmounted(() => { generation++; window.clearInterval(timer); });
</script>
