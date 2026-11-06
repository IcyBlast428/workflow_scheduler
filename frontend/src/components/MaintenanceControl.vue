<template>
<section class="surface-card maintenance-control" :class="{compact}" aria-label="执行维护模式">
  <div class="filter-actions"><strong>{{ state.enabled ? '维护模式：暂停启动新执行' : '执行接收正常' }}</strong><button v-if="!compact || controlsOpen || state.enabled" class="btn" :disabled="busy" @click="load">刷新状态</button><button v-if="!compact || controlsOpen || state.enabled" class="btn" :class="state.enabled ? 'primary' : 'warning'" :disabled="busy || state.revision == null" @click="toggle">{{ state.enabled ? '结束维护' : '进入维护' }}</button></div>
  <button v-if="compact" class="btn" :aria-expanded="controlsOpen" @click="controlsOpen=!controlsOpen">{{ controlsOpen ? '收起维护' : '维护操作' }}</button>
  <button v-if="!compact || controlsOpen || state.enabled" class="btn maintenance-expand" :aria-expanded="expanded || state.enabled" @click="expanded=!expanded">{{ expanded ? '收起说明' : '维护说明与原因' }}</button>
<div v-show="(!compact || controlsOpen) && expanded || state.enabled" class="maintenance-details"><p class="hint">运行中的任务继续完成。维护期间新触发的自动计划会取消；维护前已入队的请求保留，但等待期限继续计算，结束维护后在期限内继续派发。已超时或取消的计划不会自动补跑。</p>
  <input v-model="reason" class="input" aria-label="维护原因" placeholder="维护原因（可选）" maxlength="500" :disabled="busy">
  <p v-if="state.enabled" class="hint">{{ state.reason }} · {{ state.actor }} · {{ state.updated_at }}</p>
  </div>  <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p>
<p class="maintenance-active">活动执行 {{ state.active?.length ?? '—' }} 个{{ state.enabled && state.active?.length === 0 && state.reserved === 0 ? '，可以安排停止服务' : '' }}</p>
  <ul v-if="state.active?.length && (!compact || controlsOpen || state.enabled)"><li v-for="run in state.active" :key="run.run_id">{{ run.task_name || run.pid }} · {{ run.status === 'running' ? '运行中' : '排队中' }}</li></ul>
</section>
</template>
<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue';
import {useRefreshLoop} from '../composables/useRefreshLoop.js';
import { api } from '../api';
const props=defineProps({compact:Boolean,confirm:{type:Function,required:true}});
const expanded=ref(false), controlsOpen=ref(false);
const state=ref({}), reason=ref(''), error=ref(''), busy=ref(false);
let alive=true, generation=0, pending=null;
function load(){if(pending)return pending;pending=fetchState().finally(()=>{pending=null;});return pending;}
async function fetchState() {
  if (busy.value) return;
  const seq=++generation;
  try {
    const value=await api.admission();
    if (alive && seq===generation) { state.value=value; error.value=''; }
  } catch (err) { if (alive && seq===generation) error.value=err.message;return false; }
}
async function toggle() {
  if (busy.value) return;
  busy.value=true; generation++;
  const enabled=!state.value.enabled, revision=state.value.revision;
  try {
    const confirmed=await props.confirm({
      title:enabled?'进入维护模式':'结束维护模式',
      message:enabled?'停止接受新的任务执行，等待运行中任务完成。':'恢复派发仍在等待期限内的已有请求；维护期间取消的计划不会自动补跑。',
      confirmText:enabled?'进入维护':'恢复执行', danger:enabled,
    });
    if (!confirmed || !alive) return;
    const value=await api.setAdmission({enabled,revision,reason:reason.value});
    if (alive) { state.value=value; error.value=''; }
  } catch (err) { if (alive) error.value=err.message; }
  finally { if (alive) busy.value=false; }
}
useRefreshLoop({load,enabled:()=>!busy.value});
onBeforeUnmount(()=>{alive=false;generation++;});
</script>
<style scoped>.maintenance-control{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:16px;padding:12px 16px}.maintenance-details{order:4;flex-basis:100%;display:grid;gap:12px}.maintenance-active{margin-left:auto!important}.maintenance-expand{font-size:12px}.maintenance-control p{margin:0}.maintenance-control.compact{margin:0;padding:8px 20px;border:0;border-radius:0;border-bottom:1px solid var(--line);background:transparent;font-size:13px}.compact .btn{min-height:32px;padding:5px 10px}.compact>ul{flex-basis:100%}</style>
