<template>
  <section class="panel connection-panel">
    <div class="panel-head"><div><h2>数据库连接</h2><p>平台连接与任务业务连接分开管理；业务任务统一通过 NewDB 使用连接标识。</p></div><button class="btn" :disabled="busy || loading" @click="load">刷新</button></div>
    <nav class="connection-tabs" aria-label="数据库连接分类"><button class="btn" :class="{primary:tab==='business'}" :aria-pressed="tab==='business'" @click="tab='business'">业务数据库 · {{ profiles.length }}</button><button class="btn" :class="{primary:tab==='platform'}" :aria-pressed="tab==='platform'" @click="tab='platform'">平台数据库</button><button class="btn" :class="{primary:tab==='nacos'}" :aria-pressed="tab==='nacos'" @click="tab='nacos'">Nacos 连接</button></nav>
    <PlatformDatabase v-show="tab==='platform'" :confirm="confirm" />
    <NacosSettings v-if="nacosVisited" v-show="tab==='nacos'" :confirm="confirm" />
    <div v-show="tab==='business'" class="panel-body connection-body">
      <LoadingStatus compact :active="loading" label="正在读取连接设置…" />
      <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p><p v-if="message" class="inline-alert success" role="status">{{ message }}</p>
      <div class="connection-list-tools"><label>查找业务连接<input class="input" v-model.trim="query" placeholder="名称、标识、类型或环境" /></label><button class="btn primary" :disabled="Boolean(busy)" @click="choose(empty())">＋ 新建业务连接</button></div>
      <p class="hint connection-table-help">连接列表可左右滑动，查看类型、状态与编辑操作。</p>
      <div class="table-scroll"><table class="connection-table"><thead><tr><th>业务连接</th><th>数据库类型</th><th>环境</th><th>关联任务</th><th>状态</th><th>管理</th></tr></thead><tbody><tr v-for="item in filteredProfiles" :key="item.id" :class="{'selected-row':form.id===item.id}"><td><strong>{{ item.name || item.id }}</strong><small>{{ item.id }}</small></td><td>{{ typeLabel(item.dialect) }}<small>{{ item.source==='nacos'?'Nacos 配置':'直接配置' }}</small></td><td>{{ item.environment || '未标记' }}</td><td>{{ usages.find(u=>u.id===item.id)?.usage?.length || 0 }}</td><td><span class="tag" :class="item.enabled?'success':'info'">{{ item.archived?'已归档':item.enabled?'已启用':'已停用' }}</span></td><td><button class="btn" :disabled="Boolean(busy)" @click="choose(item)">编辑<span class="sr-only"> {{ item.id }}</span></button></td></tr><tr v-if="!filteredProfiles.length"><td colspan="6" class="hint">{{ profiles.length?'没有匹配的连接。':'尚无业务连接，请先新建，再授权给任务。' }}</td></tr></tbody></table></div>
      <section class="surface-card"><h3>支持的业务数据库</h3><div class="filter-actions"><span v-for="item in types" :key="item.dialect" class="tag" :class="item.driver_ready?'success':'info'">{{ item.label }} · {{ item.driver_ready?'驱动就绪':item.available&&item.odbc_driver?'需安装 ODBC 驱动':'需安装驱动' }}</span></div><p class="hint">任务通过连接标识使用业务数据库。驱动及事务兼容性应在对应数据库产品上验收。</p></section>
      <section v-if="form.revision" class="surface-card"><h3>连接使用与状态</h3><p>{{ form.enabled?'启用中':'已停用' }} · {{ usage?.usage?.length || 0 }} 个任务声明或获授权</p><p v-for="task in usage?.usage || []" :key="task.pid" class="hint">{{ task.name }} · {{ task.pid }}</p><p class="hint">最近测试：{{ usage?.last_test?.at || '尚无记录' }} · {{ usage?.last_test?.ready?'通过':'未通过 / 未测试' }} · {{ usage?.last_test?.elapsed_ms ?? '—' }} ms</p><p class="hint">连接状态变更对下次任务执行生效，运行中任务保留原配置；停用前请核对依赖任务。</p></section>
      <form @submit.prevent="run('save')"><h3>{{ form.revision ? '编辑业务连接 · ' + form.id : '新建业务连接' }}</h3><p v-if="!canEditForm" class="inline-alert warning">此连接来自 Nacos，当前账号仅可查看。远端读取、修改及状态管理仅限内置管理员。</p><fieldset :disabled="Boolean(busy) || loading || nacosLoading || !canEditForm">
        <label>业务配置来源<select class="select" v-model="form.source" @change="invalidateNacos"><option value="direct">直接配置</option><option value="nacos" :disabled="!canManageNacos">Nacos 配置</option></select></label>
        <NacosBindingFields v-if="form.source==='nacos'" v-model="form.nacos" :md5="form.nacos_md5" :disabled="!canEditForm || Boolean(busy) || loading" @invalidated="invalidateNacos" @loaded="loadNacos" @busy="nacosLoading=$event" />
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
        <div v-if="canEditForm" class="filter-actions"><button type="button" class="btn" :disabled="form.source==='nacos' && !form.nacos_md5" @click="run('test')">{{ busy==='test'?'测试中…':'测试连接' }}</button><button class="btn primary" type="submit" :disabled="form.source==='nacos' && !form.nacos_md5">{{ busy==='save'?'保存中…':'测试并保存' }}</button></div>
        <p v-if="form.source==='nacos'" class="hint">测试不会发布配置；保存会同步到 Nacos，其他消费者也会读到修改。停用、归档或删除仅修改本地登记，不删除 Nacos 配置。</p>
        <div v-if="form.revision && canEditForm" class="filter-actions"><button type="button" class="btn" @click="change(form.enabled?'disable':'enable')">{{ form.enabled?'停用连接':'启用连接' }}</button><button type="button" class="btn" @click="change('archive')">归档连接</button><template v-if="!form.enabled"><input v-model="confirmation" class="input" aria-label="删除连接确认" placeholder="输入完整连接标识"><button type="button" class="btn danger" :disabled="confirmation!==form.id || Boolean(usage?.usage?.length)" @click="change('delete')">删除已停用连接</button></template></div>
      </fieldset></form>
    </div>
  </section>
</template>
<script setup>
import {computed,ref,watch,onMounted,onBeforeUnmount} from 'vue';
import {api} from '../api';
import {useUnsavedChanges} from '../composables/useUnsavedChanges';
import LoadingStatus from './LoadingStatus.vue';
import PlatformDatabase from './PlatformDatabase.vue';
import NacosSettings from './NacosSettings.vue';
import NacosBindingFields from './NacosBindingFields.vue';
const props=defineProps({confirm:Function});
// 分栏通过 v-show 保留草稿；Nacos 设置首次访问时再加载，避免无关的远端管理请求。
const tab=ref('business'),query=ref(''),nacosVisited=ref(false),nacosLoading=ref(false);
watch(tab,value=>{if(value==='nacos')nacosVisited.value=true;});
const tlsLabels={disabled:'不使用 TLS',require:'TLS（仅加密）',verify_identity:'TLS（校验证书和主机名）'};
const state=ref({}),profiles=ref([]),types=ref([]),usages=ref([]),error=ref(''),message=ref(''),busy=ref(''),loading=ref(false),confirmation=ref('');
const empty=()=>({source:'direct',nacos:{},nacos_md5:'',nacos_settings_token:'',id:'',name:'',host:'',port:5432,database:'',user:'',password:'',password_set:false,dialect:'postgresql',revision:0,tls:'disabled',ssl_ca:'',pool_enabled:true,driver:'',pool_size:1,max_overflow:1,pool_recycle:600,pool_timeout:10,owner:'',purpose:'',environment:'',enabled:true});
const form=ref(empty());const {dirty,saved}=useUnsavedChanges(()=>form.value);
const canManageNacos=computed(()=>state.value.can_manage_nacos===true);
const canEditForm=computed(()=>form.value.source!=='nacos' || canManageNacos.value);
const usage=computed(()=>usages.value.find(p=>p.id===form.value.id));
const selectedType=computed(()=>types.value.find(p=>p.dialect===form.value.dialect));
const typeLabel=dialect=>types.value.find(t=>t.dialect===dialect)?.label || dialect;
const filteredProfiles=computed(()=>profiles.value.filter(p=>[p.id,p.name,p.environment,typeLabel(p.dialect)].join(' ').toLowerCase().includes(query.value.toLowerCase())));
let generation=0;
// 接口只返回 password_set；空密码表示沿用已存密文，不能把掩码当成真实密码回传。
function assign(item){form.value={...empty(),...item,nacos:JSON.parse(JSON.stringify(item.nacos||{})),nacos_md5:'',nacos_settings_token:'',password:''};confirmation.value='';saved();}
// 定位改变后旧 MD5 和密码状态不能用于另一份 JSON，必须先显式读取。
function invalidateNacos(){form.value.nacos_md5='';form.value.nacos_settings_token='';form.value.password='';if(form.value.source==='nacos')form.value.password_set=false;}
function loadNacos(result){const value=result.profile||{};for(const key of ['host','port','database','user','schema','password_set'])if(key in value)form.value[key]=value[key];form.value.password='';form.value.nacos=result.binding||form.value.nacos;form.value.nacos_md5=result.md5;form.value.nacos_settings_token=result.nacos_settings_token;message.value='已读取 Nacos 配置，可编辑连接信息后测试或同步保存。';error.value='';}
// 端口、驱动与 TLS 能力来自后端类型目录，换类型时清空不适用的旧驱动/证书设置。
function changeDialect(){form.value.port=selectedType.value?.port || 5432;form.value.driver=selectedType.value?.default_driver || '';form.value.tls='disabled';form.value.ssl_ca='';}
// 列表与使用情况一起刷新，但不改 form；后台返回不能覆盖用户正在编辑的字段。
async function load(){const seq=++generation;loading.value=true;error.value='';try{const [s,u]=await Promise.all([api.databaseConnections(),api.connectionUsage()]);if(seq!==generation)return;state.value=s;profiles.value=s.profiles;types.value=s.supported_databases;usages.value=u;}catch(e){if(seq===generation)error.value=e.message;}finally{if(seq===generation)loading.value=false;}}
async function choose(item){if(dirty.value&&!await props.confirm({title:'放弃未保存的修改？',message:'切换连接会丢失未保存内容。',confirmText:'切换',cancelText:'继续编辑'}))return;assign(item);message.value='';error.value='';}
async function run(action){if(busy.value || loading.value || nacosLoading.value || !canEditForm.value)return;const nacos=form.value.source==='nacos';if(nacos && !form.value.nacos_md5){error.value='请先读取 Nacos 配置，再测试或保存。';return;}if(action==='save' && nacos && !await props.confirm({title:'同步业务连接至 Nacos？',message:'通过数据库连接测试后，将修改同步到这份 Nacos JSON。其他消费者也会读到修改；当前运行中的任务保留原配置，下次执行读取新配置。',confirmText:'测试并同步保存'}))return;busy.value=action;error.value='';message.value='';try{const result=await api.changeDatabaseConnection(action,form.value);if(action==='save')assign(result.profile);await load();message.value=action==='save'?(result.nacos_synced?'业务连接已同步至 Nacos 并保存，下次任务执行生效，运行中任务保留原配置。':'业务连接已保存，下次任务执行生效，运行中任务保留原配置。'):'连接测试通过。'+(nacos?'尚未写入 Nacos。':'');}catch(e){error.value=e.message;}finally{busy.value='';}}
async function change(action){if(busy.value || !canEditForm.value)return;const labels={enable:'启用',disable:'停用',archive:'归档',delete:'删除'};if(!await props.confirm({title:labels[action]+'业务连接',message:form.value.id+' 将'+labels[action]+'，请核对依赖任务。'+(form.value.source==='nacos'?'此操作仅修改本地登记，不删除 Nacos 配置。':''),confirmText:'确认操作',danger:action!=='enable'}))return;busy.value=action;error.value='';try{await api.connectionLifecycle({id:form.value.id,action,revision:form.value.revision,confirm:confirmation.value});const id=form.value.id;await load();assign(profiles.value.find(p=>p.id===id)||empty());message.value='连接状态已更新。';}catch(e){error.value=e.message;}finally{busy.value='';}}
onMounted(load);onBeforeUnmount(()=>generation++);
</script>
<style scoped>
.connection-body{display:grid;gap:20px;min-width:0}.connection-body>*{min-width:0}.connection-body .tag{white-space:normal;overflow-wrap:anywhere}.connection-body .surface-card{display:grid;gap:12px}.connection-body p,.connection-body h3{margin:0}.connection-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr));gap:20px}fieldset{border:0;padding:0;margin:0;display:grid;gap:20px;min-width:0}label{display:grid;gap:8px;align-content:start}.checkbox-row{display:flex;align-items:center}.filter-actions input{max-width:300px}.filter-actions{flex-wrap:wrap}
.connection-tabs{display:flex;gap:8px;padding:16px 20px 0;flex-wrap:wrap}.connection-list-tools{display:flex;gap:16px;align-items:end;flex-wrap:wrap}.connection-list-tools label{flex:1;min-width:min(240px,100%)}.table-scroll{overflow:auto;max-width:100%}.connection-table{width:100%;border-collapse:collapse;white-space:nowrap}.connection-table td,.connection-table th{padding:12px;text-align:left;border-bottom:1px solid var(--border)}.connection-table small{display:block;opacity:.7;margin-top:4px}.connection-example{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.selected-row{background:var(--surface-hover,rgba(255,255,255,.04))}.connection-body>form{display:grid;gap:16px}
.connection-table-help{display:none}@media(max-width:640px){.connection-table-help{display:block}}
</style>
