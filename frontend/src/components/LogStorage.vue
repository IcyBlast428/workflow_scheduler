<template>
  <section class="surface-card log-storage">
    <div class="section-heading"><h3>执行日志清理</h3><p>按结束时间保留日志，每批最多清理 500 条；执行记录、统计和历史摘要保留。不会清理运行中、排队中或尚未完成历史保存的执行。</p></div>
    <div class="filter-actions"><label class="retention-field">日志至少保留（天）<input v-model.number="days" class="input" type="number" min="7" max="3650" :disabled="busy" @input="invalidate" /></label><button class="btn" :disabled="busy" @click="preview">{{ busy ? '处理中…' : '预览日志清理' }}</button></div>
    <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p>
    <p v-if="message" class="inline-alert success" role="status">{{ message }}</p>
    <template v-if="plan">
      <div class="admin-metrics"><div class="mini-stat"><span>本批可清理</span><strong>{{ plan.count }} 条</strong></div><div class="mini-stat"><span>预计释放</span><strong>{{ size(plan.bytes) }}</strong></div><div class="mini-stat"><span>已检查执行</span><strong>{{ plan.inspected }} 条</strong></div></div>
      <p class="hint">结束时间早于 {{ plan.cutoff.split('.')[0] }}。{{ plan.missing }} 条日志为空或文件已不存在，仅更新清理标记。后台现有自动保留期为 {{ plan.automatic_retention_days }} 天，由运维部署配置管理；此处预览不改变自动保留期。</p>
      <p v-if="plan.partial" class="inline-alert warning">本次为有上限的分批检查，并非全部日志占用；完成本批后请再次预览。</p>
      <p v-if="plan.skipped" class="hint">已跳过 {{ plan.skipped }} 条不满足条件或路径无法安全清理的执行。</p>
      <template v-if="plan.count"><p>删除的日志文件不可恢复；需要留档请先下载或备份。计划十分钟有效。</p><label>输入“{{ plan.confirm }}”确认<input v-model="confirmation" class="input" aria-label="日志清理确认文字" :disabled="busy" /></label><button class="btn danger" :disabled="busy || confirmation!==plan.confirm" @click="cleanup">清理本批执行日志</button></template>
      <p v-else class="hint">本次检查未发现可清理日志。</p>
    </template>
  </section>
</template>
<script setup>
import {ref} from 'vue';
import {api} from '../api';
const days=ref(90),plan=ref(null),confirmation=ref(''),error=ref(''),message=ref(''),busy=ref(false);
const size=value=>`${(value/1024**2).toFixed(1)} MiB`;
function invalidate(){plan.value=null;confirmation.value='';message.value='';}
async function preview(){busy.value=true;invalidate();error.value='';try{plan.value=await api.logStorage(days.value);}catch(e){error.value=e.message;}finally{busy.value=false;}}
async function cleanup(){busy.value=true;error.value='';try{const result=await api.cleanLogs({token:plan.value.token,confirm:confirmation.value});invalidate();message.value=`已清理 ${result.count} 条，释放 ${size(result.bytes)}；${result.skipped} 条发生变化或无法处理，已跳过。可再次预览下一批。`;}catch(e){error.value=e.message;}finally{busy.value=false;}}
</script>
<style scoped>.log-storage{margin-bottom:24px}.log-storage .input{max-width:300px}.log-storage .retention-field{display:grid;gap:8px;flex:0 0 190px}.retention-field .input{width:120px}.log-storage .filter-actions{align-items:end}.log-storage>label{display:grid;gap:8px;margin:12px 0}.log-storage p{line-height:1.7}</style>
