<template>
  <section class="panel connection-panel">
    <div class="panel-head"><div><h2>数据库连接</h2><p>平台连接与任务业务连接分开管理；业务任务统一通过 NewDB 使用连接标识。</p></div><button class="btn" :disabled="busy || loading" @click="load">刷新</button></div>
    <nav class="connection-tabs" aria-label="数据库连接分类"><button class="btn" :class="{primary:tab==='business'}" :aria-pressed="tab==='business'" @click="tab='business'">业务数据库 · {{ profiles.length }}</button><button class="btn" :class="{primary:tab==='platform'}" :aria-pressed="tab==='platform'" @click="tab='platform'">平台数据库</button></nav>
    <PlatformDatabase v-show="tab==='platform'" :confirm="confirm" />
    <div v-show="tab==='business'" class="panel-body connection-body">
      <LoadingStatus compact :active="loading" label="正在读取连接设置…" />
      <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p><p v-if="message" class="inline-alert success" role="status">{{ message }}</p>
      <div class="connection-list-tools"><label>查找业务连接<input class="input" v-model.trim="query" placeholder="名称、标识、类型或环境" /></label><button class="btn primary" :disabled="Boolean(busy)" @click="choose(empty())">＋ 新建业务连接</button></div>
      <p class="hint connection-table-help">连接列表可左右滑动，查看类型、状态与编辑操作。</p>
      <div class="table-scroll"><table class="connection-table"><thead><tr><th>业务连接</th><th>数据库类型</th><th>环境</th><th>关联任务</th><th>状态</th><th>管理</th></tr></thead><tbody><tr v-for="item in filteredProfiles" :key="item.id" :class="{'selected-row':form.id===item.id}"><td><strong>{{ item.name || item.id }}</strong><small>{{ item.id }}</small></td><td>{{ typeLabel(item.dialect) }}</td><td>{{ item.environment || '未标记' }}</td><td>{{ usages.find(u=>u.id===item.id)?.usage?.length || 0 }}</td><td><span class="tag" :class="item.enabled?'success':'info'">{{ item.archived?'已归档':item.enabled?'已启用':'已停用' }}</span></td><td><button class="btn" :disabled="Boolean(busy)" @click="choose(item)">编辑<span class="sr-only"> {{ item.id }}</span></button></td></tr><tr v-if="!filteredProfiles.length"><td colspan="6" class="hint">{{ profiles.length?'没有匹配的连接。':'尚无业务连接，请先新建，再授权给任务。' }}</td></tr></tbody></table></div>
      <section class="surface-card"><h3>支持的业务数据库</h3><div class="filter-actions"><span v-for="item in types" :key="item.dialect" class="tag" :class="item.driver_ready?'success':'info'">{{ item.label }} · {{ item.driver_ready?'驱动就绪':item.available&&item.odbc_driver?'需安装 ODBC 驱动':'需安装驱动' }}</span></div><p class="hint">任务通过连接标识使用业务数据库。驱动及事务兼容性应在对应数据库产品上验收。</p></section>
      <section v-if="form.revision" class="surface-card"><h3>连接使用与状态</h3><p>{{ form.enabled?'启用中':'已停用' }} · {{ usage?.usage?.length || 0 }} 个任务声明或获授权</p><p v-for="task in usage?.usage || []" :key="task.pid" class="hint">{{ task.name }} · {{ task.pid }}</p><p class="hint">最近测试：{{ usage?.last_test?.at || '尚无记录' }} · {{ usage?.last_test?.ready?'通过':'未通过 / 未测试' }} · {{ usage?.last_test?.elapsed_ms ?? '—' }} ms</p><p class="hint">连接状态变更对下次任务执行生效，运行中任务保留原配置；停用前请核对依赖任务。</p></section>
      <form @submit.prevent="run('save')"><h3>{{ form.revision ? '编辑业务连接 · ' + form.id : '新建业务连接' }}</h3><fieldset :disabled="busy || loading">
        <div class="connection-grid">
          <label>连接标识<input aria-label="连接标识" v-model.trim="form.id" class="input" required :readonly="Boolean(form.revision)" pattern="[A-Za-z][A-Za-z0-9_-]{0,99}" maxlength="100" placeholder="例如 reports"><small class="hint">已有连接标识不能修改。</small></label>
          <label>连接名称<input v-model.trim="form.name" class="input" maxlength="100"></label>
          <label>数据库类型<select aria-label="数据库类型" v-model="form.dialect" class="select" @change="changeDialect"><option v-for="item in types" :key="item.dialect" :value="item.dialect">{{ item.label }}</option></select><small class="hint">{{ selectedType?.package }}{{ selectedType?.available===false?' · 服务器需安装驱动':'' }}</small></label>
          <label>数据库地址<input v-model.trim="form.host" class="input" required maxlength="253" placeholder="主机名或 IP"></label>
          <label>端口<input v-model.number="form.port" class="input" type="number" required min="1" max="65535"></label>
          <label>{{ selectedType?.database_label || '数据库名称' }}<input v-model.trim="form.database" class="input" required maxlength="64"></label>
          <label>数据库用户名<input v-model.trim="form.user" class="input" required maxlength="100" autocomplete="off"></label>
          <label>数据库密码<input aria-label="数据库密码" v-model="form.password" type="password" class="input" :required="!form.password_set" maxlength="1024" autocomplete="new-password" :placeholder="form.password_set?'留空保留原密码':''"><small class="hint">密码加密保存，接口不回传原文。</small></label>
          <label>负责人<input v-model.trim="form.owner" class="input" maxlength="100"></label><label>用途<input v-model.trim="form.purpose" class="input" maxlength="500"></label><label>环境标签<input v-model.trim="form.environment" class="input" maxlength="30"></label>
          <label v-if="selectedType?.odbc_driver">ODBC 驱动名称<input v-model.trim="form.driver" class="input" required maxlength="120" :placeholder="selectedType.default_driver" /><small class="hint">{{ selectedType.driver_ready?'服务端驱动就绪':'请在服务端和任务环境安装对应驱动' }}</small></label>
          <label>连接加密<select v-model="form.tls" class="select"><option v-for="mode in selectedType?.tls_modes || ['disabled','verify_identity']" :key="mode" :value="mode">{{ tlsLabels[mode] }}</option></select><small v-if="selectedType?.tls_note" class="hint">{{ selectedType.tls_note }}</small></label>
          <label v-if="form.tls==='verify_identity' && selectedType?.ca_file!==false">服务器 CA 证书路径<input v-model.trim="form.ssl_ca" class="input" required><small class="hint">Web、调度和任务环境均须可读。</small></label>
        </div>
        <details class="disclosure"><summary>连接池设置</summary><div class="disclosure-body"><label class="checkbox-row"><input v-model="form.pool_enabled" type="checkbox">启用连接池</label><div v-if="form.pool_enabled" class="connection-grid"><label>常驻连接上限<input v-model.number="form.pool_size" class="input" type="number" min="1" max="20" required></label><label>临时额外连接上限<input v-model.number="form.max_overflow" class="input" type="number" min="0" max="20" required></label><label>连接回收周期（秒）<input v-model.number="form.pool_recycle" class="input" type="number" min="30" max="3600" required></label><label>等待空闲连接（秒）<input v-model.number="form.pool_timeout" class="input" type="number" min="1" max="120" required></label></div><p class="hint">同一进程复用连接池，各任务子进程独立计数，请按任务并发评估业务库连接数。</p></div></details>
        <div class="filter-actions"><button type="button" class="btn" @click="run('test')">{{ busy==='test'?'测试中…':'测试连接' }}</button><button class="btn primary" type="submit">{{ busy==='save'?'保存中…':'测试并保存' }}</button></div>
        <div v-if="form.revision" class="filter-actions"><button type="button" class="btn" @click="change(form.enabled?'disable':'enable')">{{ form.enabled?'停用连接':'启用连接' }}</button><button type="button" class="btn" @click="change('archive')">归档连接</button><template v-if="!form.enabled"><input v-model="confirmation" class="input" aria-label="删除连接确认" placeholder="输入完整连接标识"><button type="button" class="btn danger" :disabled="confirmation!==form.id || Boolean(usage?.usage?.length)" @click="change('delete')">删除已停用连接</button></template></div>
      </fieldset></form>
      <section class="surface-card"><h3>任务中的统一用法</h3><pre class="connection-example">from app.common.database import NewDB

with NewDB("{{ form.id || '连接标识' }}") as db:
    rows = db.query("SELECT 1")</pre><p class="hint">先在任务详情中授权此连接。新数据库连接可直接在本页添加；新的数据库类型需要先接入对应适配器和驱动。页面不保存任务内的连接密码。</p></section>
    </div>
  </section>
</template>
<script setup>
import {computed,ref,onMounted,onBeforeUnmount} from 'vue';
import {api} from '../api';
import {useUnsavedChanges} from '../composables/useUnsavedChanges';
import LoadingStatus from './LoadingStatus.vue';
import PlatformDatabase from './PlatformDatabase.vue';
const props=defineProps({confirm:Function});
// 两个分栏通过 v-show 保持挂载，切换平台/业务连接时保留各自未保存的编辑内容。
const tab=ref('business'),query=ref('');
const tlsLabels={disabled:'不使用 TLS',require:'TLS（仅加密）',verify_identity:'TLS（校验证书和主机名）'};
const state=ref({}),profiles=ref([]),types=ref([]),usages=ref([]),error=ref(''),message=ref(''),busy=ref(''),loading=ref(false),confirmation=ref('');
const empty=()=>({id:'',name:'',host:'',port:5432,database:'',user:'',password:'',password_set:false,dialect:'postgresql',revision:0,tls:'disabled',ssl_ca:'',pool_enabled:true,driver:'',pool_size:1,max_overflow:1,pool_recycle:600,pool_timeout:10,owner:'',purpose:'',environment:'',enabled:true});
const form=ref(empty());const {dirty,saved}=useUnsavedChanges(()=>form.value);
const usage=computed(()=>usages.value.find(p=>p.id===form.value.id));
const selectedType=computed(()=>types.value.find(p=>p.dialect===form.value.dialect));
const typeLabel=dialect=>types.value.find(t=>t.dialect===dialect)?.label || dialect;
const filteredProfiles=computed(()=>profiles.value.filter(p=>[p.id,p.name,p.environment,typeLabel(p.dialect)].join(' ').toLowerCase().includes(query.value.toLowerCase())));
let generation=0;
// 接口只返回 password_set；空密码表示沿用已存密文，不能把掩码当成真实密码回传。
function assign(item){form.value={...empty(),...item,password:''};confirmation.value='';saved();}
// 端口、驱动与 TLS 能力来自后端类型目录，换类型时清空不适用的旧驱动/证书设置。
function changeDialect(){form.value.port=selectedType.value?.port || 5432;form.value.driver=selectedType.value?.default_driver || '';form.value.tls='disabled';form.value.ssl_ca='';}
// 列表与使用情况一起刷新，但不改 form；后台返回不能覆盖用户正在编辑的字段。
async function load(){const seq=++generation;loading.value=true;error.value='';try{const [s,u]=await Promise.all([api.databaseConnections(),api.connectionUsage()]);if(seq!==generation)return;state.value=s;profiles.value=s.profiles;types.value=s.supported_databases;usages.value=u;}catch(e){if(seq===generation)error.value=e.message;}finally{if(seq===generation)loading.value=false;}}
async function choose(item){if(dirty.value&&!await props.confirm({title:'放弃未保存的修改？',message:'切换连接会丢失未保存内容。',confirmText:'切换',cancelText:'继续编辑'}))return;assign(item);message.value='';error.value='';}
async function run(action){if(busy.value)return;busy.value=action;error.value='';message.value='';try{const result=await api.changeDatabaseConnection(action,form.value);if(action==='save')assign(result.profile);await load();message.value=action==='save'?'业务连接已保存，下次任务执行生效，运行中任务保留原配置。':'连接测试通过。';}catch(e){error.value=e.message;}finally{busy.value='';}}
async function change(action){if(busy.value)return;const labels={enable:'启用',disable:'停用',archive:'归档',delete:'删除'};if(!await props.confirm({title:labels[action]+'业务连接',message:form.value.id+' 将'+labels[action]+'，请核对依赖任务。',confirmText:'确认操作',danger:action!=='enable'}))return;busy.value=action;error.value='';try{await api.connectionLifecycle({id:form.value.id,action,revision:form.value.revision,confirm:confirmation.value});const id=form.value.id;await load();assign(profiles.value.find(p=>p.id===id)||empty());message.value='连接状态已更新。';}catch(e){error.value=e.message;}finally{busy.value='';}}
onMounted(load);onBeforeUnmount(()=>generation++);
</script>
<style scoped>
.connection-body{display:grid;gap:20px;min-width:0}.connection-body>*{min-width:0}.connection-body .tag{white-space:normal;overflow-wrap:anywhere}.connection-body .surface-card{display:grid;gap:12px}.connection-body p,.connection-body h3{margin:0}.connection-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr));gap:20px}fieldset{border:0;padding:0;margin:0;display:grid;gap:20px;min-width:0}label{display:grid;gap:8px;align-content:start}.checkbox-row{display:flex;align-items:center}.filter-actions input{max-width:300px}.filter-actions{flex-wrap:wrap}
.connection-tabs{display:flex;gap:8px;padding:16px 20px 0;flex-wrap:wrap}.connection-list-tools{display:flex;gap:16px;align-items:end;flex-wrap:wrap}.connection-list-tools label{flex:1;min-width:min(240px,100%)}.table-scroll{overflow:auto;max-width:100%}.connection-table{width:100%;border-collapse:collapse;white-space:nowrap}.connection-table td,.connection-table th{padding:12px;text-align:left;border-bottom:1px solid var(--border)}.connection-table small{display:block;opacity:.7;margin-top:4px}.connection-example{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.selected-row{background:var(--surface-hover,rgba(255,255,255,.04))}.connection-body>form{display:grid;gap:16px}
.connection-table-help{display:none}@media(max-width:640px){.connection-table-help{display:block}}
</style>
