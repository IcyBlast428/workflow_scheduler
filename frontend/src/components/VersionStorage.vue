<template>
  <section class="surface-card">
    <div class="section-heading"><h3>任务版本占用</h3><p>检查代码、依赖环境与回收站的空间占用，并预览保留范围。</p></div>
    <div class="filter-actions"><label class="storage-keep">每个任务至少保留最近 <input v-model.number="keep" class="input" type="number" min="20" max="500" aria-label="保留版本数"> 个版本</label><button class="btn" :disabled="loading" @click="load">{{ loading ? '正在检查…' : '检查版本占用' }}</button></div>
    <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p>
    <template v-if="data"><div class="admin-metrics"><div class="mini-stat"><span>已扫描占用</span><strong>{{ size(data.bytes) }}</strong></div><div class="mini-stat"><span>其中回收站</span><strong>{{ size(data.trash_bytes) }}</strong></div><div class="mini-stat"><span>保留范围外候选</span><strong>{{ size(data.candidate_bytes) }}</strong></div></div>
      <p class="hint">{{ data.message }}</p><p v-if="data.truncated" class="inline-alert warning">本次达到扫描上限，显示已扫描部分；未完整检查的版本不会列为候选。</p>
      <div class="table-wrap storage-table"><table><thead><tr><th>任务</th><th>版本</th><th>占用</th><th>保留依据</th></tr></thead><tbody><tr v-for="item in data.versions" :key="item.pid+item.version"><td>{{ item.name }}<small class="cell-subtitle">{{ item.trash ? '回收站' : item.pid }}</small></td><td class="mono">{{ item.version.slice(0,12) }}</td><td>{{ size(item.bytes) }}{{ item.complete ? '' : '（部分）' }}</td><td>{{ item.protected.join('、') || '保留范围外，须核对历史追溯需求' }}</td></tr></tbody></table><p v-if="!data.versions.length" class="hint">尚无已管理的任务版本。</p></div>
    </template>
  </section>
</template>
<script setup>
import { ref } from 'vue'; import { api } from '../api';
const keep = ref(20), data = ref(null), loading = ref(false), error = ref('');
const size = value => `${(value/1024**2).toFixed(1)} MiB`;
async function load() { if (loading.value) return; loading.value = true; try { data.value = await api.storage(keep.value); error.value = ''; } catch (err) { error.value = err.message; } finally { loading.value = false; } }
</script>
