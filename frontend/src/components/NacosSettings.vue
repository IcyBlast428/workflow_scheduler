<template>
  <section class="panel-body nacos-settings">
    <LoadingStatus compact :active="loading" label="正在读取 Nacos 设置…" />
    <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p><p v-if="message" class="inline-alert success" role="status">{{ message }}</p>
    <section class="surface-card"><div class="nacos-heading"><h3>Nacos 2.x 连接</h3><span class="tag" :class="state.configured?'success':'info'">{{ state.configured?'已配置':'待配置' }}</span><button class="btn" :disabled="loading || Boolean(busy)" @click="refresh">刷新设置</button></div><p>平台数据库与业务数据库共用此 Nacos 连接，分别指定命名空间、分组和 Data ID。</p><p class="hint">仅内置管理员 {{ state.editor_username || 'admin' }} 可修改 Nacos 设置或读取、同步远端配置。{{ canEdit?'账号凭据加密保存在服务器，页面不回显原密码。':'当前账号仅可查看连接设置。' }}</p></section>
    <form v-if="state.profile" class="surface-card" @submit.prevent="run('save')"><fieldset :disabled="!canEdit || loading || Boolean(busy)">
      <h3>{{ canEdit?'编辑 Nacos 连接':'Nacos 连接设置（只读）' }}</h3>
      <label>Nacos 服务地址<input class="input" v-model.trim="form.url" type="url" required placeholder="http://nacos.internal:8848/nacos" autocomplete="off" /><small class="hint">包含实际上下文路径，例如 /nacos。</small></label>
      <label class="checkbox-row"><input v-model="form.auth_enabled" type="checkbox" />启用 Nacos 账号认证</label>
      <div v-if="form.auth_enabled" class="nacos-grid"><label>Nacos 用户名<input class="input" v-model.trim="form.username" required autocomplete="off" /></label><label>Nacos 密码<input class="input" v-model="form.password" type="password" :required="!form.password_set" autocomplete="new-password" :placeholder="form.password_set?'留空保留原密码':''" /></label></div>
      <details class="disclosure" :open="!form.auth_enabled"><summary>探测配置{{ form.auth_enabled?'（可选）':'（未启用认证时必填）' }}</summary><div class="disclosure-body nacos-options"><p class="hint">仅读取这份配置来验证访问权限，不修改内容。开启认证时可留空，仅验证账号认证；关闭认证时需指定一份可读取的配置。</p><div class="nacos-grid"><label>探测命名空间 ID<input class="input" v-model.trim="form.probe_binding.namespace" placeholder="留空使用 public" /></label><label>探测配置分组<input class="input" v-model.trim="form.probe_binding.group" :required="!form.auth_enabled || Boolean(form.probe_binding.data_id)" placeholder="DEFAULT_GROUP" /></label><label>探测 Data ID<input class="input" v-model.trim="form.probe_binding.data_id" :required="!form.auth_enabled" placeholder="例如 reports-db.json" /></label></div></div></details>
      <details class="disclosure"><summary>TLS 与读取设置</summary><div class="disclosure-body nacos-options"><label class="checkbox-row"><input v-model="form.verify_tls" type="checkbox" />HTTPS 校验证书</label><div class="nacos-grid"><label v-if="form.verify_tls">Nacos CA 证书路径<input class="input" v-model.trim="form.ca_file" placeholder="留空使用系统证书" /><small class="hint">证书文件须可被平台服务读取。</small></label><label>请求超时（秒）<input class="input" type="number" v-model.number="form.timeout" min="1" max="60" required /></label><label>配置缓存（秒）<input class="input" type="number" v-model.number="form.config_ttl" min="0" max="3600" required /><small class="hint">缓存减少远端请求；0 表示不缓存。</small></label></div></div></details>
      <p class="hint">保存后，后续 Nacos 读取使用新设置。平台数据库连接仍需完整重启服务后生效；运行中的业务任务继续使用启动时的配置。</p>
      <div v-if="canEdit" class="filter-actions"><button type="button" class="btn" @click="run('test')">{{ busy==='test'?'测试中…':'测试 Nacos 连接' }}</button><button class="btn primary" type="submit">{{ busy==='save'?'保存中…':'保存 Nacos 设置' }}</button></div>
    </fieldset></form>
  </section>
</template>
<script setup>
import {computed,onBeforeUnmount,onMounted,ref} from 'vue';
import {api} from '../api';
import {useUnsavedChanges} from '../composables/useUnsavedChanges';
import LoadingStatus from './LoadingStatus.vue';
const props=defineProps({confirm:Function});
const state=ref({}),form=ref({}),loading=ref(false),busy=ref(''),error=ref(''),message=ref('');
const canEdit=computed(()=>state.value.can_edit===true);
const {dirty,saved}=useUnsavedChanges(()=>form.value,()=>canEdit.value && Boolean(state.value.profile));let generation=0;
async function load(){const seq=++generation;loading.value=true;error.value='';try{const data=await api.nacos();if(seq!==generation)return;state.value=data;form.value={...data.profile,password:'',probe_binding:form.value.probe_binding||{namespace:'',group:'DEFAULT_GROUP',data_id:''}};saved();}catch(e){if(seq===generation)error.value=e.message;}finally{if(seq===generation)loading.value=false;}}
async function refresh(){if(dirty.value && !await props.confirm({title:'重新读取 Nacos 设置？',message:'当前未保存的修改将被替换。',confirmText:'重新读取',cancelText:'继续编辑'}))return;await load();}
async function run(action){if(!canEdit.value || loading.value || busy.value)return;if(!form.value.auth_enabled && !form.value.probe_binding.data_id){error.value='未启用认证时，请填写用于验证读取权限的探测 Data ID。';return;}if(action==='save' && !await props.confirm({title:'保存 Nacos 连接设置？',message:'后续配置读取将使用新设置，请确认绑定的数据库配置在目标 Nacos 中存在。平台数据库在完整重启后生效。',confirmText:'保存设置'}))return;busy.value=action;error.value='';message.value='';try{const body={...form.value,probe_binding:form.value.probe_binding.data_id?form.value.probe_binding:undefined};const result=await api.changeNacos(action,body);if(action==='save'){await load();message.value='Nacos 连接设置已加密保存，后续读取使用新设置。';}else message.value=result.verified==='authentication'?'Nacos 账号认证通过，尚未验证具体配置的读取及发布权限。':result.verified==='config_read'?'Nacos 配置读取验证通过；本次测试未发布配置。':'Nacos 服务可访问，请读取具体配置以验证访问权限。';}catch(e){error.value=e.message;}finally{busy.value='';}}
onMounted(load);onBeforeUnmount(()=>generation++);
</script>
<style scoped>
.nacos-settings,.nacos-settings .surface-card,.nacos-settings fieldset,.nacos-options{display:grid;gap:16px;min-width:0}.nacos-settings fieldset{border:0;margin:0;padding:0}.nacos-settings h3,.nacos-settings p{margin:0;overflow-wrap:anywhere}.nacos-settings label{display:grid;gap:8px;align-content:start;min-width:0}.nacos-settings .checkbox-row{display:flex;align-items:center}.nacos-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr));gap:16px}.nacos-heading{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.nacos-heading h3{margin-right:auto}.nacos-settings .filter-actions{flex-wrap:wrap}
</style>
