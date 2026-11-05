<template>
  <ModalShell :embedded="embedded" :open="Boolean(runId)" :label="`本次执行：${record.task_name || record.pid || '加载中'}`" panel-class="execution-modal" backdrop-class="" @close="$emit('close')">
      <header class="modal-head"><div><h3>本次执行：{{ record.task_name || record.pid || '加载中' }}</h3><p class="hint mono">{{ runId }}</p></div>
        <button class="btn icon-only" title="关闭" @click="$emit('close')">×</button></header>
      <div class="modal-body">
        <LoadingStatus :active="initialLoading" label="正在读取执行详情与日志…" />
        <div v-if="error" class="inline-alert danger">{{ error }} <button class="btn" @click="refresh(true)">重试</button></div>
        <section v-if="record.status" class="workbench-summary" aria-label="执行摘要">
          <div><small>执行结果</small><strong><span class="tag" :class="statusClass(record.status)">{{ statusLabel(record.status) }}</span></strong></div>
          <div><small>执行耗时</small><strong>{{ elapsed }}</strong></div>
          <div><small>任务代码版本</small><strong class="mono" :title="record.code_version?.task_release">{{ record.code_version?.task_release?.slice(0,12) || '未记录' }}</strong></div>
        </section>
        <div v-if="reason || failureHint" class="inline-alert warning execution-reason"><strong>{{ reason ? '执行说明' : '日志中的错误线索' }}</strong><p>{{ reason.length > 320 ? reason.slice(0,320) + '…' : reason || failureHint }}</p></div>
        <div class="filter-actions execution-content-tabs" aria-label="执行内容切换">
          <button class="btn" :class="contentView === 'logs' ? 'primary' : ''" :aria-pressed="contentView === 'logs'" @click="contentView='logs'">执行日志</button>
          <button class="btn" :class="contentView === 'outputs' ? 'primary' : ''" :aria-pressed="contentView === 'outputs'" @click="outputsVisited=true;contentView='outputs'">输出文件</button>
          <button v-if="canOperate && record.status && !['queued','running'].includes(record.status)" class="btn" :disabled="retrying" @click="$emit('retry',record)">再执行一次</button>
        </div>
        <details v-if="record.status" class="disclosure"><summary>执行时间、来源与版本信息</summary><div class="disclosure-body"><div class="execution-meta">
          <span>来源：{{ ({manual:'手动',trial:'试运行',retry:'自动重试',backfill:'业务日期补跑'})[record.source] || '自动调度' }} · {{ record.actor }}</span>
          <span>开始：{{ record.start_time || '尚未开始' }}</span><span>结束：{{ record.end_time || '尚未结束' }}</span>
          <span>最近心跳：{{ record.heartbeat || '-' }}</span>
          <span>计划：{{ record.scheduled_time || record.created_at || '-' }} · 启动延迟：{{ record.start_delay_seconds?.toFixed(2) ?? '-' }} 秒</span>
        </div><p v-if="reason.length > 320" class="execution-reason">{{ reason }}</p>
        <details v-if="record.code_version" class="disclosure"><summary>本次执行的代码与环境</summary><div class="disclosure-body"><p>平台版本：{{ record.code_version.release }} · {{ record.code_version.python }}</p><p v-if="record.code_version.task_release" class="mono">任务版本 {{ record.code_version.task_release }} · 包 SHA256 {{ record.code_version.package_sha256 }}</p><p class="mono">入口 {{ record.code_version.entry }} · SHA256 {{ record.code_version.entry_sha256 }}</p><p class="mono">依赖摘要 {{ record.code_version.dependency_sha256 }}</p><p class="hint">代码查看页显示当前文件；历史执行以此处版本和摘要为准。</p></div></details>
        <p v-if="record.business_date" class="hint">业务日期：{{ record.business_date }} · 重试次数：{{ record.retry_attempt || 0 }}</p>
        <p v-if="record.code_version?.shared_sdk_sha256" class="hint mono">公共 SDK：{{ record.code_version.shared_sdk_package || '冻结快照' }} · {{ record.code_version.shared_sdk_sha256 }}</p>
        </div></details>
        <p v-if="record.log_truncated" class="hint">保留日志已达到容量上限，后续输出已丢弃。</p>
        <div v-show="contentView === 'logs'" class="execution-log-panel">
        <p v-if="logUnavailable" class="hint">{{ record.log_cleaned_at ? '日志文件已清理，执行记录和历史摘要仍然保留。' : '日志尚未生成或已超过保留期限。' }}</p>
        <p v-else class="hint">{{ historical ? '正在分段查看历史日志' : '默认展示日志末尾，页面最多保留最近 256 KiB' }} · 文件大小 {{ (logSize/1024).toFixed(1) }} KiB。搜索仅针对当前已加载内容，完整内容可下载查看。</p>
        <div class="filter-actions" aria-label="日志分段导航"><button class="btn" :disabled="initialLoading || inFlight || !pageStart" @click="showPage(0)">日志开头</button><button class="btn" :disabled="initialLoading || inFlight || !pageStart" @click="showPage(Math.max(0,pageStart-65536))">较早一段</button><button class="btn" :disabled="initialLoading || inFlight || !historical || offset>=logSize" @click="showPage(offset)">较后一段</button><button class="btn" :disabled="initialLoading || inFlight || logUnavailable" @click="showPage('tail')">最新日志</button></div>
        <div class="filter-actions"><input v-model="search" class="input" placeholder="搜索当前日志片段" aria-label="搜索当前日志片段">
          <label><input v-model="follow" type="checkbox">自动滚动</label>
          <a v-if="!logUnavailable" class="btn" :href="`/api/taskinfo/run-download?run_id=${runId}`" download>下载保留日志</a></div>
        <pre ref="logElement" class="log-pre execution-output">{{ filtered || emptyExecutionLog(record.status, search) }}</pre>
        </div>
        <TaskArtifacts v-if="outputsVisited" v-show="contentView === 'outputs'" :key="runId" :run-id="runId" :status="record.status" />
      </div>
  </ModalShell>
</template>
<script setup>
import ModalShell from './ModalShell.vue';
import TaskArtifacts from './TaskArtifacts.vue';
import { ref, computed, watch, onUnmounted, nextTick } from 'vue';
import { timestamp } from '../timebase';
import { api } from '../api';
import LoadingStatus from './LoadingStatus.vue';
import { statusLabel, statusClass, emptyExecutionLog } from '../executionLabels';
const props = defineProps({ embedded: Boolean, runId: { type: String, default: '' }, canOperate:Boolean, retrying:Boolean });
defineEmits(['close','retry']);
const record = ref({}), content = ref(''), error = ref(''), search = ref(''), follow = ref(true), logElement = ref(null);
const reason = computed(() => String(record.value.reason || '').trim());
const elapsed=computed(()=>{const seconds=(timestamp(record.value.end_time)-timestamp(record.value.start_time))/1000;return Number.isFinite(seconds)&&seconds>=0?`${seconds.toFixed(1)} 秒`:'—';});
const failureHint=computed(()=>['failed','timed_out','interrupted'].includes(record.value.status)&&!record.value.reason ? content.value.split('\n').reverse().find(line=>/\b(?:error|exception|traceback)\b|失败|异常/i.test(line))?.trim().slice(0,320) || '' : '');
const initialLoading = ref(false), contentView=ref('logs'),outputsVisited=ref(false);
const pageStart=ref(0), logSize=ref(0), logUnavailable=ref(false), historical=ref(false), offset=ref('tail'), inFlight=ref(false);
let timer, generation = 0;
const filtered = computed(() => search.value ? content.value.split('\n').filter(line => line.toLowerCase().includes(search.value.toLowerCase())).join('\n') : content.value);
async function refresh(manual=false) {
  if (!props.runId || inFlight.value || historical.value && manual!==true || document.visibilityState === 'hidden') return;
  inFlight.value = true;
  const seq = generation;
  try {
    const result = await api.execution(props.runId, offset.value);
    if (seq !== generation) return;
    record.value = result.record;
    if (!content.value) pageStart.value=result.start_offset;
    logSize.value=result.log_size; logUnavailable.value=result.log_unavailable;
    content.value += result.content;
    offset.value = result.next_offset;
    const encoded=new TextEncoder().encode(content.value);
    if (encoded.length > 256 * 1024) { let start=encoded.length-256*1024;while((encoded[start]&0xc0)===0x80)start++;content.value=new TextDecoder().decode(encoded.slice(start));pageStart.value=offset.value-(encoded.length-start); }
    error.value = '';
    await nextTick();
    if (follow.value && logElement.value) logElement.value.scrollTop = logElement.value.scrollHeight;
    if (!['queued','running'].includes(record.value.status) && !result.has_more) window.clearInterval(timer);
  } catch (err) { if (seq === generation) error.value = err.message; }
  finally { inFlight.value = false; if (seq === generation) initialLoading.value = false; }
}
function showPage(position){historical.value=position!=='tail';offset.value=position;content.value='';initialLoading.value=true;refresh(true);}
watch(() => props.runId, () => {
  contentView.value='logs';outputsVisited.value=false;search.value='';
  generation++; window.clearInterval(timer); offset.value = 'tail'; historical.value=false; pageStart.value=0;logSize.value=0;logUnavailable.value=false; content.value = ''; record.value = {}; error.value = '';
  initialLoading.value = Boolean(props.runId);
  if (props.runId) { timer = window.setInterval(refresh, 1500); refresh(); }
}, { immediate: true });
onUnmounted(() => { generation++; window.clearInterval(timer); });
</script>
