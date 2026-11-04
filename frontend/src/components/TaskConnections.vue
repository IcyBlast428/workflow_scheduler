<template>
<section class="task-connection-access" aria-label="任务连接授权">
  <h3>任务业务连接授权</h3><p class="hint">任务默认无业务数据库权限。选中需要的连接后保存，下次执行生效。</p>
  <p class="inline-alert warning">此授权控制平台 SDK 和凭据注入，不是操作系统沙箱。任务代码仍须经过可信审核。</p>
  <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p><p v-if="message" role="status">{{ message }}</p>
  <fieldset :disabled="busy"><p class="hint">仅允许指定连接</p>
  <div v-if="form.mode === 'restricted'" class="connection-options"><label v-for="item in available" :key="item.id" class="checkbox-row"><input v-model="form.connections" type="checkbox" :value="item.id">{{ item.id }} · {{ item.dialect }}</label><p class="hint">未选择连接时，禁止通过平台 SDK 使用业务数据库。</p></div>
  <button class="btn primary" :disabled="form.revision == null" @click="save">保存授权</button></fieldset>
</section>
</template>
<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'; import { api } from '../api';
import {useUnsavedChanges} from '../composables/useUnsavedChanges';
const props=defineProps({pid:String,confirm:Function});const form=ref({}),available=ref([]),error=ref(''),message=ref(''),busy=ref(false);let generation=0;
const {saved:grantSaved}=useUnsavedChanges(()=>form.value,()=>form.value.revision!=null);
watch(()=>props.pid,async pid=>{const seq=++generation;busy.value=true;message.value='';error.value='';form.value={};try{const data=await api.taskConnections(pid);if(seq===generation){form.value=data.grant;available.value=data.available;grantSaved();}}catch(e){if(seq===generation)error.value=e.message;}finally{if(seq===generation)busy.value=false;}},{immediate:true});
async function save(){const seq=generation;if(!await props.confirm({title:'更新任务连接授权',message:'下一次执行只会提供选中的业务连接。',confirmText:'保存授权',danger:true}))return;if(seq!==generation)return;busy.value=true;try{const data=await api.saveTaskConnections(props.pid,form.value);if(seq===generation){form.value=data.grant;grantSaved();message.value='授权已保存，下次执行生效。';error.value='';}}catch(e){if(seq===generation)error.value=e.message;}finally{if(seq===generation)busy.value=false;}}
onBeforeUnmount(()=>generation++);
</script>
<style scoped>fieldset{border:0;padding:0;margin:0;min-width:0;display:grid;gap:16px}.task-connection-access{display:grid;gap:12px}.task-connection-access label,.connection-options{display:grid;gap:12px}.task-connection-access label.checkbox-row{display:flex}.task-connection-access h3,.task-connection-access p{margin:0}</style>
