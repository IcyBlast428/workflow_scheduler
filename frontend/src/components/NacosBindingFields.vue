<template>
  <section class="nacos-binding surface-card">
    <div class="binding-heading"><h3>Nacos 配置定位</h3><span class="tag" :class="md5?'success':'info'">{{ md5?'已读取，可测试与同步':'待读取' }}</span></div>
    <p class="hint">每个数据库对应一份 JSON。先读取配置，再编辑连接信息；保存时同步回 Nacos。</p>
    <div class="binding-grid">
      <label>命名空间 ID<input class="input" :value="binding.namespace" @input="update('namespace',$event.target.value.trim())" placeholder="留空使用 public" :disabled="disabled || loading" autocomplete="off" /><small class="hint">填写 namespace ID，不是显示名称。</small></label>
      <label>配置分组<input class="input" :value="binding.group" @input="update('group',$event.target.value.trim())" :disabled="disabled || loading" placeholder="DEFAULT_GROUP" required /></label>
      <label>配置 Data ID<input class="input" :value="binding.data_id" @input="update('data_id',$event.target.value.trim())" :disabled="disabled || loading" placeholder="例如 reports-db.json" required /></label>
    </div>
    <details class="disclosure"><summary>字段映射与密码编码</summary><div class="disclosure-body binding-grid">
      <label v-for="field in fieldLabels" :key="field.key">{{ field.label }}对应字段<input class="input" :value="binding.fields[field.key]" @input="updateField(field.key,$event.target.value.trim())" :disabled="disabled || loading" :placeholder="defaults.fields[field.key]" :required="field.key!=='schema'" /></label>
      <label>Nacos 密码编码<select class="select" :value="binding.password_encoding" @change="update('password_encoding',$event.target.value)" :disabled="disabled || loading"><option value="plain">原文</option><option value="base64">Base64</option></select><small class="hint">按现有 JSON 选择；Base64 是编码方式，不是加密。</small></label>
    </div></details>
    <p v-if="!md5" class="hint">{{ disabled?'当前账号仅可查看此绑定。':'定位或字段映射发生变化后，需要重新读取。' }}</p>
    <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p>
    <div v-if="!disabled" class="filter-actions"><button class="btn" type="button" :disabled="loading || !binding.data_id || !binding.group" @click="read">{{ loading?'正在读取…':md5?'重新读取 Nacos 配置':'读取 Nacos 配置' }}</button></div>
  </section>
</template>
<script setup>
import {computed,onBeforeUnmount,ref,watch} from 'vue';
import {api} from '../api';
const props=defineProps({modelValue:Object,md5:String,disabled:Boolean});
const emit=defineEmits(['update:modelValue','invalidated','loaded','busy']);
const defaults={namespace:'',group:'DEFAULT_GROUP',data_id:'',password_encoding:'plain',fields:{host:'host',port:'port',database:'db',user:'user',password:'password',schema:'schema'}};
const fieldLabels=[{key:'host',label:'数据库地址'},{key:'port',label:'端口'},{key:'database',label:'数据库名称'},{key:'user',label:'用户名'},{key:'password',label:'密码'},{key:'schema',label:'Schema（可选）'}];
const binding=computed(()=>({...defaults,...props.modelValue,fields:{...defaults.fields,...props.modelValue?.fields}}));
const loading=ref(false),error=ref('');let generation=0;
// 仅用户编辑触发版本作废；父页面载入另一份草稿时只取消过期的读取响应。
function update(key,value){error.value='';emit('update:modelValue',{...binding.value,[key]:value});emit('invalidated');}
function updateField(key,value){update('fields',{...binding.value.fields,[key]:value});}
watch(()=>props.modelValue,()=>{generation++;loading.value=false;emit('busy',false);error.value='';},{deep:true});
async function read(){if(props.disabled || loading.value)return;const seq=++generation;const snapshot=JSON.stringify(binding.value);loading.value=true;emit('busy',true);error.value='';try{const result=await api.previewNacos({binding:JSON.parse(snapshot)});if(seq!==generation || snapshot!==JSON.stringify(binding.value))return;emit('loaded',result);}catch(e){if(seq===generation)error.value=e.message;}finally{if(seq===generation){loading.value=false;emit('busy',false);}}}
onBeforeUnmount(()=>{generation++;emit('busy',false);});
</script>
<style scoped>
.nacos-binding{display:grid;gap:14px;min-width:0}.nacos-binding h3,.nacos-binding p{margin:0;overflow-wrap:anywhere}.binding-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.binding-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(210px,100%),1fr));gap:16px}.binding-grid label{display:grid;gap:8px;min-width:0;align-content:start}.nacos-binding .filter-actions{flex-wrap:wrap}
</style>
