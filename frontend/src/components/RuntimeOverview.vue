<template>
  <section class="panel attention-panel" :class="{'is-clear': !loading && !error && data.scheduler?.healthy && !data.issues?.length}">
    <div class="panel-head"><div><h2>需要处理</h2><p>配置、执行和服务维护的待处理事项。</p></div><button class="btn" :disabled="loading" @click="load">刷新</button></div>
    <div class="panel-body">
      <div class="runtime-alerts"><span class="tag" :class="data.scheduler?.healthy ? 'success' : 'warning'">调度器：{{ data.scheduler?.healthy ? '正常' : data.scheduler?.message || '检测中' }}</span><span class="tag info">业务时区：Asia/Shanghai · UTC+8</span><span class="tag info">数据库：{{ data.database || '-' }}</span></div>
      <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p>
      <p v-else-if="!data.issues?.length" class="hint">{{ loading ? '正在检查运行状态…' : '当前未发现需要处理的事项。' }}</p>
      <ul v-else class="attention-list"><li v-for="item in data.issues" :key="item.key"><div><strong>{{ item.title }}</strong><p>{{ item.message }}</p><small v-if="item.resolution?.note" class="hint">已处理：{{ item.resolution.note }} · {{ item.resolution.actor }}</small><small v-if="item.time" class="muted">{{ item.time }}</small></div><button v-if="item.run_id" class="btn" @click="$emit('execution',item.run_id)">查看执行</button><button v-else-if="item.pid" class="btn" @click="$emit('detail',item.pid)">查看任务</button><button v-else-if="canManage" class="btn" @click="$emit('admin')">运行维护</button><button v-if="canManage && !item.resolution?.note" class="btn" @click="resolving=item.key;note=''">记录处理结果</button><div v-if="resolving===item.key" class="attention-resolution"><input v-model="note" class="input" aria-label="异常处理说明" maxlength="1000"><button class="btn" :disabled="!note" @click="resolve(item.key)">保存处理结果</button></div></li></ul>
      <p v-if="data.truncated" class="hint">仅展示最近的部分事项，完整记录可在执行记录中查询。</p>
    </div>
  </section>
</template>
<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue';
import { api } from '../api';
defineProps({ canManage: Boolean }); defineEmits(['detail','execution','admin']);
const resolving=ref(''),note=ref('');
const data = ref({}), error = ref(''), loading = ref(false); let timer, stopped = false;
async function load() {
  if (loading.value || stopped || document.visibilityState === 'hidden') return;
  loading.value = true;
  try { const result = await api.attention(); if (!stopped) { data.value = result; error.value = ''; } }
  catch (err) { if (!stopped) error.value = err.message; }
  finally { if (!stopped) loading.value = false; }
}
async function resolve(key){try{await api.resolveIssue({key,note:note.value});resolving.value='';await load();}catch(e){error.value=e.message;}}
onMounted(() => { load(); timer = setInterval(load,30000); });
onBeforeUnmount(() => { stopped = true; clearInterval(timer); });
</script>
