<template>
 <section class="execution-matrix-workspace">
  <nav class="matrix-workspace-tabs surface-card" aria-label="任务执行分栏">
   <button v-for="item in tabs" :key="item.id" class="btn" :class="{primary:tab===item.id}" :aria-pressed="tab===item.id" @click="$emit('select',item.id)">{{ item.label }}</button>
  </nav>
  <RecentExecutionMatrix v-if="visited.has('recent')" v-show="tab==='recent'" :active="tab==='recent'" @task="$emit('task',$event)" @record="$emit('record',$event)" @history="$emit('history',$event)" />
  <ExecutionMatrix v-if="visited.has('timeline')" v-show="tab==='timeline'" :active="tab==='timeline'" :user-key="userKey" @task="$emit('task',$event)" @execution="$emit('execution',$event)" @logs="$emit('logs',$event)" />
  <div v-if="visited.has('logs')" v-show="tab==='logs'" class="execution-records-pane"><slot name="logs" /></div>
  <ExecutionQueue v-if="visited.has('queue') && canManage" v-show="tab==='queue'" :active="tab==='queue'" :confirm="confirm" @detail="$emit('task',$event)" @execution="$emit('execution',$event)" @settings="$emit('settings')" />
 </section>
</template>
<script setup>
import {computed,reactive,watch} from 'vue';
import ExecutionMatrix from './ExecutionMatrix.vue';
import RecentExecutionMatrix from './RecentExecutionMatrix.vue';
import ExecutionQueue from './ExecutionQueue.vue';
const props=defineProps({userKey:String,canManage:Boolean,confirm:Function,selectedTab:String});
defineEmits(['task','execution','logs','settings','select','record','history']);
const tabs=computed(()=>[{id:'recent',label:'最近结果'},{id:'timeline',label:'当日轨迹'},{id:'logs',label:'执行记录'},...(props.canManage?[{id:'queue',label:'执行队列'}]:[])]);
const tab=computed(()=>tabs.value.some(item=>item.id===props.selectedTab)?props.selectedTab:'recent');
const visited=reactive(new Set());
watch(tab,value=>visited.add(value),{immediate:true});
</script>
<style scoped>.execution-matrix-workspace{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;min-width:0}.matrix-workspace-tabs{display:flex;gap:10px;flex-wrap:wrap;padding:14px 18px}</style>
