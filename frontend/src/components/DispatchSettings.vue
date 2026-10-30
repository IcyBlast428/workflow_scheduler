<template>
<details class="disclosure dispatch-settings">
<summary>任务排队与负载保护</summary>
<div class="disclosure-body">
<p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p><p v-if="message" role="status">{{ message }}</p>
<p class="hint">自动计划持久排队，按原定时间先后尝试派发。达到并发名额会等待；等待超时或队列已满会明确提示，不会无限积压。</p>
<form @submit.prevent="save"><fieldset :disabled="busy || !loaded">
<div class="filter-grid">
<label>全局并发名额<input v-model.number="form.max_active" class="input" type="number" min="1" max="20"></label>
<label>相邻进程启动间隔（毫秒）<input v-model.number="form.start_interval_ms" class="input" type="number" min="100" max="60000"></label>
<label>队列最多等待请求<input v-model.number="form.max_pending" class="input" type="number" min="1" max="10000"></label>
<label>单任务最多等待请求<input v-model.number="form.max_pending_per_task" class="input" type="number" min="1" max="1000"></label>
<label>最长等待（秒）<input v-model.number="form.max_wait_seconds" class="input" type="number" min="1" max="86400"></label>
</div>
<p class="hint">自动计划还受自身允许迟到时间约束，取较短值；错峰时间计入等待期限。修改等待期限只影响新请求。环境中的并发上限仍有效；已有运行不会被中止。</p>
<label class="checkbox-row"><input v-model="form.load_protection" type="checkbox">主机持续高负载时暂缓启动</label>
<div v-if="form.load_protection" class="filter-grid"><label>CPU 暂缓阈值（%）<input v-model.number="form.cpu_high" class="input" type="number" min="20" max="99"></label><label>内存暂缓阈值（%）<input v-model.number="form.memory_high" class="input" type="number" min="20" max="99"></label></div>
<p class="hint">连续 3 次高负载采样后暂停启动；CPU 低于阈值 10 个百分点、内存低于阈值 5 个百分点，连续 3 次后恢复。采样异常时等待。此保护不能限制已运行任务的 CPU，重任务可另设 systemd 资源配额。</p>
<button class="btn primary" style="justify-self:start" type="submit">保存排队策略</button>
</fieldset></form>
<p class="hint">查看等待原因和执行去向，请使用左侧“执行队列”。</p>
</div></details>
</template>
<script setup>
import { ref,onMounted,onBeforeUnmount } from 'vue';
import { api } from '../api';
import { useUnsavedChanges } from '../composables/useUnsavedChanges';
const form=ref({}),error=ref(''),message=ref(''),loaded=ref(false),busy=ref(false);
const {saved}=useUnsavedChanges(()=>form.value,()=>loaded.value);
let alive=true;
async function save(){busy.value=true;error.value='';try{form.value=await api.saveOperationalPolicy('dispatch',form.value);saved();message.value='排队策略已保存；已有任务继续运行。';}catch(e){error.value=e.message;}finally{busy.value=false;}}
onMounted(async()=>{try{const value=await api.operationalPolicy('dispatch');if(alive){form.value=value;loaded.value=true;saved();}}catch(e){if(alive)error.value=e.message;}});
onBeforeUnmount(()=>{alive=false;});
</script>
<style scoped>
.dispatch-settings fieldset{display:grid;gap:16px;margin:0;padding:0;border:0;min-width:0}.dispatch-settings label{display:grid;gap:8px}.dispatch-settings .checkbox-row{display:flex}.dispatch-settings .filter-grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}.dispatch-settings .queue-task{max-width:220px;overflow-wrap:anywhere}.dispatch-settings p,.dispatch-settings h4{margin:0}
</style>
