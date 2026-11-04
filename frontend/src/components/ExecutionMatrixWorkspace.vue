<template>
 <section class="execution-matrix-workspace">
  <nav class="matrix-workspace-tabs surface-card" aria-label="执行矩阵分栏">
   <button v-for="item in tabs" :key="item.id" class="btn" :class="{primary:tab===item.id}" :aria-pressed="tab===item.id" @click="select(item.id)">{{ item.label }}</button>
  </nav>
  <RecentExecutionMatrix v-if="tab==='recent'" @task="$emit('task',$event)" @logs="$emit('logs',$event)" />
  <ExecutionMatrix v-else-if="tab==='timeline'" :user-key="userKey" @task="$emit('task',$event)" @execution="$emit('execution',$event)" @logs="$emit('logs',$event)" />
  <ExecutionQueue v-else-if="canManage" :confirm="confirm" @detail="$emit('task',$event)" @execution="$emit('execution',$event)" @settings="$emit('settings')" />
 </section>
</template>
<script setup>
import {computed,ref,onMounted,onBeforeUnmount} from 'vue';
import ExecutionMatrix from './ExecutionMatrix.vue';
import RecentExecutionMatrix from './RecentExecutionMatrix.vue';
import ExecutionQueue from './ExecutionQueue.vue';
const props=defineProps({userKey:String,canManage:Boolean,confirm:Function});
defineEmits(['task','execution','logs','settings']);
const tabs=computed(()=>[{id:'recent',label:'最近 10 次'},{id:'timeline',label:'当日轨迹'},...(props.canManage?[{id:'queue',label:'执行队列'}]:[])]);
const tab=ref('recent');
function read(){const id=location.hash.split('?')[0]==='#queue'?'queue':new URLSearchParams(location.hash.split('?')[1] || '').get('tab');tab.value=tabs.value.some(item=>item.id===id)?id:'recent';}
function select(id){tab.value=id;history.replaceState(null,'',location.pathname+'#matrix?tab='+id);}
read();onMounted(()=>window.addEventListener('hashchange',read));onBeforeUnmount(()=>window.removeEventListener('hashchange',read));
</script>
<style scoped>.execution-matrix-workspace{display:grid;gap:16px;min-width:0}.matrix-workspace-tabs{display:flex;gap:10px;flex-wrap:wrap;padding:14px 18px}</style>
