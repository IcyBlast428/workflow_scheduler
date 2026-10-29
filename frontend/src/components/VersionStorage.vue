<template>
  <section class="surface-card version-storage">
    <div class="section-heading"><h3>任务版本占用</h3><p>检查代码、依赖环境与回收站的空间占用，并预览保留范围。</p></div>
    <div class="filter-actions"><label class="storage-keep">每个任务至少保留最近 <input v-model.number="keep" class="input" type="number" min="20" max="500" aria-label="保留版本数"> 个版本</label><button class="btn" :disabled="loading" @click="load">{{ loading ? '正在检查…' : '检查版本占用' }}</button></div>
    <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p>
    <template v-if="data"><div class="admin-metrics"><div class="mini-stat"><span>已扫描占用</span><strong>{{ size(data.bytes) }}</strong></div><div class="mini-stat"><span>其中回收站</span><strong>{{ size(data.trash_bytes) }}</strong></div><div class="mini-stat"><span>保留范围外候选</span><strong>{{ size(data.candidate_bytes) }}</strong></div></div>
      <p class="hint">{{ data.message }}</p><p v-if="data.truncated" class="inline-alert warning">本次达到扫描上限，显示已扫描部分；未完整检查的版本不会列为候选。</p>
      <div class="table-wrap storage-table"><table><thead><tr><th>任务</th><th>版本</th><th>占用</th><th>保留依据</th></tr></thead><tbody><tr v-for="item in data.versions" :key="item.pid+item.version"><td>{{ item.name }}<small class="cell-subtitle">{{ item.trash ? '回收站' : item.pid }}</small></td><td class="mono">{{ item.version.slice(0,12) }}</td><td>{{ size(item.bytes) }}{{ item.complete ? '' : '（部分）' }}</td><td>{{ item.protected.join('、') || '保留范围外，须核对历史追溯需求' }}</td></tr></tbody></table><p v-if="!data.versions.length" class="hint">尚无已管理的任务版本。</p></div>
    </template>
    <details class="disclosure"><summary>清理未引用的旧版本</summary><div class="disclosure-body"><p class="hint">需先进入维护模式并等待活动实例结束。只清理完整扫描且没有保留依据的版本，保留审计元数据。</p><button class="btn" :disabled="loading" @click="previewCleanup">生成清理计划</button><template v-if="plan"><p>候选 {{ plan.candidates.length }} 个 · {{ size(plan.bytes) }}</p><p v-if="plan.truncated" class="inline-alert warning">扫描不完整，不能在线清理。大规模执行历史可在停止服务后使用部署手册中的完整引用检查工具。</p><p>输入“{{ plan.confirm }}”确认：</p><input v-model="confirmation" class="input" aria-label="清理确认文字"><button class="btn danger" :disabled="loading || plan.truncated || !plan.candidates.length || confirmation !== plan.confirm" @click="cleanup">执行清理计划</button></template></div></details>
  </section>
</template>
<script setup>
import { ref } from 'vue'; import { api } from '../api';
const plan=ref(null),confirmation=ref('');
const keep = ref(20), data = ref(null), loading = ref(false), error = ref('');
const size = value => `${(value/1024**2).toFixed(1)} MiB`;
async function load() { if (loading.value) return; loading.value = true; try { data.value = await api.storage(keep.value); error.value = ''; } catch (err) { error.value = err.message; } finally { loading.value = false; } }
async function previewCleanup(){loading.value=true;try{plan.value=await api.cleanupPlan(keep.value);confirmation.value='';error.value='';}catch(e){error.value=e.message;}finally{loading.value=false;}}
async function cleanup(){loading.value=true;try{await api.cleanupVersions({keep:plan.value.keep,fingerprint:plan.value.fingerprint,confirm:confirmation.value});plan.value=null;error.value='';}catch(e){error.value=e.message;}finally{loading.value=false;await load();}}
</script>
