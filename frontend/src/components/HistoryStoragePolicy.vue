<template>
  <section class="surface-card history-storage-policy">
    <div class="section-heading"><h3>历史记录与日志摘要</h3><p>控制新增日志摘要大小，并分批归档较早的执行记录。</p></div>
    <LoadingStatus compact :active="loading" label="正在读取历史存储策略…" />
    <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p><p v-if="message" class="inline-alert success" role="status">{{ message }}</p>
    <form @submit.prevent="save"><fieldset :disabled="loading || busy"><div class="storage-grid"><label>成功执行摘要上限（KiB）<input class="input" type="number" v-model.number="form.success_excerpt_kib" min="0" max="16" required /><small class="hint">0 表示仅保存摘要提示，完整日志文件按原保留规则管理。</small></label><label>失败执行摘要上限（KiB）<input class="input" type="number" v-model.number="form.failure_excerpt_kib" min="1" max="63" required /><small class="hint">优先保留错误原因和末尾输出。通知内容保留原有额度。</small></label></div><label class="checkbox-row"><input type="checkbox" v-model="form.archive_enabled" />启用历史自动归档</label><p class="hint">归档转移到同一数据库的归档表，执行记录中仍可查询。它减少在线表负担，不释放数据库总空间；本功能不删除历史记录。</p><div v-if="form.archive_enabled" class="storage-grid"><label>在线记录至少保留（天）<input class="input" type="number" v-model.number="form.online_days" min="90" max="3650" required /></label><label>每批归档上限（条）<input class="input" type="number" v-model.number="form.archive_batch_size" min="1" max="1000" required /></label><label>每轮最大批次数<input class="input" type="number" v-model.number="form.archive_batches_per_cycle" min="1" max="50" required /></label><label>每轮时间预算（秒）<input class="input" type="number" v-model.number="form.archive_budget_seconds" min="1" max="30" required /><small class="hint">在完整批次之间检查；单批事务会执行完成或回滚。</small></label></div><div class="filter-actions"><button class="btn primary" type="submit">{{ busy?'保存中…':'保存历史存储策略' }}</button><button class="btn" type="button" @click="load(false)">刷新归档状态</button></div></fieldset></form>
    <div class="storage-status"><p>最近一轮：{{ status.last_run || '尚未运行' }} · 归档 {{ status.moved || 0 }} 条 · {{ status.batches || 0 }} 批 · {{ status.duration_ms || 0 }} ms</p><p v-if="status.error" class="inline-alert warning">{{ status.error }}</p><p v-else-if="status.has_more" class="hint">仍有待归档记录，下一轮继续处理。{{ status.budget_exhausted?'本轮已到时间预算。':'' }}</p><p class="hint">启用后，调度服务每分钟检查一次。摘要策略仅作用于后续保存的执行记录。</p></div>
  </section>
</template>
<script setup>
import {onMounted,onBeforeUnmount,ref} from 'vue';
import {api} from '../api';
import {useUnsavedChanges} from '../composables/useUnsavedChanges';
import LoadingStatus from './LoadingStatus.vue';
const form=ref({}),status=ref({}),loading=ref(false),busy=ref(false),error=ref(''),message=ref('');
const {saved}=useUnsavedChanges(()=>form.value,()=>form.value.revision!=null);let generation=0;
async function load(assign=true){const seq=++generation;loading.value=true;error.value='';try{const result=await api.historyStorage();if(seq!==generation)return;status.value=result.status;if(assign){form.value=result.policy;saved();}}catch(e){if(seq===generation)error.value=e.message;}finally{if(seq===generation)loading.value=false;}}
async function save(){if(busy.value)return;busy.value=true;error.value='';message.value='';try{const result=await api.saveHistoryStorage(form.value);form.value=result.policy;status.value=result.status;saved();message.value='历史存储策略已保存；后续执行和归档轮次使用新设置。';}catch(e){error.value=e.message;}finally{busy.value=false;}}
onMounted(load);onBeforeUnmount(()=>generation++);
</script>
<style scoped>
.history-storage-policy{display:grid;gap:16px;margin-bottom:24px}.history-storage-policy h3,.history-storage-policy p{margin:0}.history-storage-policy fieldset{border:0;padding:0;margin:0;display:grid;gap:16px;min-width:0}.storage-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr));gap:16px}.history-storage-policy label{display:grid;gap:8px;align-content:start}.history-storage-policy .checkbox-row{display:flex;align-items:center}.storage-status{display:grid;gap:8px}.history-storage-policy .filter-actions{flex-wrap:wrap}
</style>
