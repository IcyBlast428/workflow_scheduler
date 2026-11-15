<template>
  <section class="surface-card database-usage-examples">
    <div class="examples-heading"><h3>{{ kind==='platform'?'平台数据库开发示例':'任务中的统一用法' }}</h3><button type="button" class="btn" @click="copy">{{ copied?'已复制':'复制示例' }}</button></div>
    <p class="hint">{{ kind==='platform'?'仅用于平台内部开发，任务代码必须使用“任务示例与文档”中的 NewDB 示例，不能访问平台内部库。':'先在任务详情中授权连接，再通过 NewDB 使用连接标识。直接配置与 Nacos 来源使用相同写法。' }}</p>
    <slot name="settings" />
    <label>示例类型<select class="select" aria-label="示例类型" v-model="selected"><option v-for="example in examples" :key="example.id" :value="example.id">{{ example.title }}</option></select></label>
    <p>{{ current?.description }}</p><pre :class="{'connection-example':kind==='business'}"><code>{{ current?.code }}</code></pre>
    <p v-if="current?.note" class="hint">{{ current.note }}</p><p v-if="copyError" class="inline-alert warning" role="status">{{ copyError }}</p>
    <p class="hint">示例仅供复制参考，页面不会执行 SQL。请按实际表结构调整，并在测试库验证。</p>
  </section>
</template>
<script setup>
import {computed,ref,watch} from 'vue';
import {databaseExamples} from '../databaseExamples';
const props=defineProps({kind:{type:String,default:'business'},connectionId:String,dialect:String});
const examples=computed(()=>databaseExamples({kind:props.kind,connectionId:props.connectionId,dialect:props.dialect}));
const selected=ref('query'),copied=ref(false),copyError=ref('');
const current=computed(()=>examples.value.find(item=>item.id===selected.value)||examples.value[0]);
watch(current,()=>{copied.value=false;copyError.value='';if(!examples.value.some(item=>item.id===selected.value))selected.value=examples.value[0]?.id;});
// 内网 HTTP 不保证 Clipboard API 可用；临时文本域提供同一复制操作的兼容路径。
async function copy(){copied.value=false;copyError.value='';const text=current.value?.code;if(!text)return;try{if(navigator.clipboard?.writeText){try{await navigator.clipboard.writeText(text);copied.value=true;return;}catch{/* 继续使用 HTTP 可用的复制方式。 */}}const active=document.activeElement;const textarea=document.createElement('textarea');textarea.value=text;textarea.setAttribute('readonly','');textarea.style.cssText='position:fixed;left:-9999px;top:0;';document.body.appendChild(textarea);let ok=false;try{textarea.select();ok=document.execCommand('copy');}finally{textarea.remove();active?.focus();}if(!ok)throw new Error('copy');copied.value=true;}catch{copyError.value='未能自动复制，请选中下方代码手动复制。';}}
</script>
<style scoped>
.database-usage-examples{display:grid;gap:14px;min-width:0}.database-usage-examples h3,.database-usage-examples p{margin:0;overflow-wrap:anywhere}.examples-heading{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.database-usage-examples label{display:grid;gap:8px;max-width:340px;min-width:0}.database-usage-examples pre{margin:0;padding:16px;border-radius:var(--radius-md,12px);background:var(--surface-inset,rgba(0,0,0,.2));border:1px solid var(--border);white-space:pre-wrap;overflow-wrap:anywhere;min-width:0;font-size:12px;line-height:1.7}.database-usage-examples code{font:inherit}
</style>
