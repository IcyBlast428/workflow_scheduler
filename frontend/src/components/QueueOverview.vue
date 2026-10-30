<template><section class="queue-overview surface-card" aria-label="任务派发概况"><div><strong>执行队列</strong><p v-if="error" class="hint" role="alert">{{ error }}</p><p v-else class="hint">占用名额 {{ state.active || 0 }} / {{ state.max_active || '—' }} · 等待派发 {{ state.counts?.pending || 0 }} · 最长等待 {{ Math.floor((state.oldest_wait_seconds || 0)/60) }} 分 · 近 24 小时未启动 {{ (state.counts?.expired || 0)+(state.counts?.rejected || 0) }}</p></div><button class="btn" @click="$emit('queue')">查看队列</button></section></template>
<script setup>
import {ref,onMounted,onBeforeUnmount} from 'vue';import {api} from '../api';
defineEmits(['queue']);const state=ref({}),error=ref('');let alive=true,timer,busy=false;
async function load(){if(busy || document.hidden)return;busy=true;try{const result=await api.dispatchStatus();if(alive){state.value=result;error.value='';}}catch(e){if(alive)error.value=e.message;}finally{busy=false;}}
onMounted(()=>{load();timer=setInterval(load,10000);});onBeforeUnmount(()=>{alive=false;clearInterval(timer);});
</script><style scoped>.queue-overview{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:16px}.queue-overview p{margin:8px 0 0}</style>
