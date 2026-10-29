<template>
<section class="surface-card maintenance-control" aria-label="执行维护模式">
  <div class="filter-actions"><strong>{{ state.enabled ? '维护模式：暂停启动新执行' : '执行接收正常' }}</strong><button class="btn" :disabled="busy" @click="load">刷新状态</button><button class="btn" :class="state.enabled ? 'primary' : 'warning'" :disabled="busy || state.revision == null" @click="toggle">{{ state.enabled ? '结束维护' : '进入维护' }}</button></div>
  <p class="hint">维护期间，运行中的任务继续完成；尚未启动的计划会记为跳过，恢复后不自动补跑。维护状态在重启后保留。</p>
  <input v-model="reason" class="input" aria-label="维护原因" placeholder="维护原因（可选）" maxlength="500" :disabled="busy">
  <p v-if="state.enabled" class="hint">{{ state.reason }} · {{ state.actor }} · {{ state.updated_at }}</p>
  <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p>
  <p>活动执行 {{ state.active?.length ?? '—' }} 个{{ state.enabled && state.active?.length === 0 && state.reserved === 0 ? '，可以安排停止服务' : '' }}</p>
  <ul v-if="state.active?.length"><li v-for="run in state.active" :key="run.run_id">{{ run.task_name || run.pid }} · {{ run.status === 'running' ? '运行中' : '排队中' }}</li></ul>
</section>
</template>
<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue';
import { api } from '../api';
const props=defineProps({confirm:{type:Function,required:true}});
const state=ref({}), reason=ref(''), error=ref(''), busy=ref(false);
let alive=true, timer, generation=0;
async function load() {
  if (busy.value) return;
  const seq=++generation;
  try {
    const value=await api.admission();
    if (alive && seq===generation) { state.value=value; error.value=''; }
  } catch (err) { if (alive && seq===generation) error.value=err.message; }
}
async function toggle() {
  if (busy.value) return;
  busy.value=true; generation++;
  const enabled=!state.value.enabled, revision=state.value.revision;
  try {
    const confirmed=await props.confirm({
      title:enabled?'进入维护模式':'结束维护模式',
      message:enabled?'停止接受新的任务执行，等待运行中任务完成。':'恢复接受任务执行，维护期间跳过的任务不会自动补跑。',
      confirmText:enabled?'进入维护':'恢复执行', danger:enabled,
    });
    if (!confirmed || !alive) return;
    const value=await api.setAdmission({enabled,revision,reason:reason.value});
    if (alive) { state.value=value; error.value=''; }
  } catch (err) { if (alive) error.value=err.message; }
  finally { if (alive) busy.value=false; }
}
onMounted(()=>{load();timer=setInterval(()=>{if(!document.hidden)load();},5000);});
onBeforeUnmount(()=>{alive=false;generation++;clearInterval(timer);});
</script>
<style scoped>.maintenance-control{display:grid;gap:12px;margin-bottom:16px}.maintenance-control p{margin:0}</style>
