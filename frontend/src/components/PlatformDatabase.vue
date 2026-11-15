<template>
  <section class="panel-body platform-database">
    <LoadingStatus compact :active="loading" label="正在读取平台数据库配置…" />
    <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p>
    <p v-if="message" class="inline-alert success" role="status">{{ message }}</p>
    <template v-if="state.active">
      <section class="surface-card">
        <div class="platform-heading">
          <div class="section-heading"><h3>平台数据库 · GaussDB / DWS</h3><p>保存账户、任务配置、队列和执行历史。业务任务使用独立授权的 NewDB 连接。</p></div>
          <button v-if="canEdit && form.source === 'service'" class="btn primary" :disabled="loading || Boolean(busy)" @click="customize">自定义平台连接</button>
        </div>
        <p>当前来源：{{ sourceLabels[state.active.source] || '服务配置 / Nacos' }} · 当前版本 {{ state.active.revision }}</p>
        <p v-if="state.active.source!=='service'" class="hint">{{ state.active.host }}:{{ state.active.port }} / {{ state.active.database }} / {{ state.active.schema }}</p>
        <p v-else class="hint">{{ state.active.db_id }}</p>
        <p class="hint platform-access">仅内置管理员 {{ state.editor_username || 'admin' }} 可测试和修改平台连接。{{ canEdit ? '可在下方直接配置地址、库名、账号与连接池。' : '当前账号仅可查看配置与连接池状态。' }}</p>
        <p v-if="state.restart_required" class="inline-alert warning">已有版本 {{ state.saved?.revision }} 的待生效配置。完整重启平台服务后生效。</p>
        <p v-if="state.test_environment" class="hint">当前是本机独立协议测试环境；生产连接测试需要对应的 GaussDB/DWS 驱动和数据库。</p>
      </section>
      <form class="surface-card" @submit.prevent="run('save')">
        <fieldset :disabled="!canEdit || loading || Boolean(busy) || nacosLoading">
          <h3>{{ canEdit ? '编辑平台连接' : '平台连接配置（只读）' }}</h3>
          <label>配置来源<select class="select" v-model="form.source" @change="invalidateNacos"><option value="service">沿用服务配置 / Nacos</option><option value="direct">自定义连接</option><option value="nacos">Nacos 配置</option></select></label>
          <NacosBindingFields v-if="form.source==='nacos'" v-model="form.nacos" :md5="form.nacos_md5" :disabled="!canEdit || loading || Boolean(busy)" @invalidated="invalidateNacos" @loaded="loadNacos" @busy="nacosLoading=$event" />
          <div class="platform-grid">
            <label v-if="form.source==='service'">服务数据库标识<input class="input" v-model.trim="form.db_id" required placeholder="database_schema" /><small class="hint">沿用服务中的数据库标识；Nacos 服务地址可在“Nacos 连接”中统一管理。</small></label>
            <template v-else>
              <label>平台数据库地址<input ref="hostInput" class="input" v-model.trim="form.host" required placeholder="数据库主机名或 IP" /></label>
              <label>平台数据库端口<input class="input" v-model.number="form.port" type="number" min="1" max="65535" required /></label>
              <label>平台数据库名称<input class="input" v-model.trim="form.database" required /></label>
              <label>平台 Schema<input class="input" v-model.trim="form.schema" required /></label>
              <label>平台数据库账号<input class="input" v-model.trim="form.user" required autocomplete="off" /></label>
              <label>平台数据库密码<input class="input" v-model="form.password" type="password" :required="!form.password_set" autocomplete="new-password" :placeholder="form.password_set?'留空保留原密码':''" /></label>
            </template>
            <label>平台 ODBC 驱动<input class="input" v-model.trim="form.driver" required list="platform-drivers" /><datalist id="platform-drivers"><option v-for="driver in state.drivers || []" :key="driver" :value="driver" /></datalist></label>
          </div>
          <details class="disclosure">
            <summary>平台连接池与超时</summary>
            <div class="disclosure-body platform-grid"><label v-for="field in poolFields" :key="field.key">{{ field.label }}<input class="input" type="number" v-model.number="form[field.key]" :min="field.min" :max="field.max" required /></label></div>
            <p class="hint">连接池按进程独立计数。当前标准部署有 2 个 Web 工作进程、1 个调度工作进程；容量预算合计为 {{ capacity }} 个平台连接，按需建立。</p>
          </details>
          <p class="inline-alert warning">保存前会验证目标库结构。修改只保存为待重启配置，不迁移现有数据。更换目标库前，请先完成数据迁移与备份；随后完整重启平台服务。</p>
          <p v-if="form.source==='nacos'" class="hint">测试不发布配置；保存会同步到 Nacos，其他消费者也会读到修改。当前平台连接保持不变，完整重启后生效。</p>
          <div v-if="canEdit" class="filter-actions"><button type="button" class="btn" :disabled="form.source==='nacos' && !form.nacos_md5" @click="run('test')">{{ busy==='test'?'测试中…':'测试平台连接' }}</button><button class="btn primary" type="submit" :disabled="form.source==='nacos' && !form.nacos_md5">{{ busy==='save'?'保存中…':'测试并保存待重启配置' }}</button></div>
        </fieldset>
      </form>
      <DatabaseUsageExamples kind="platform" dialect="gaussdb" />
      <section class="surface-card">
        <div class="platform-heading"><h3>连接池运行状态</h3><button class="btn" :disabled="loading || Boolean(busy)" @click="load(false)">刷新连接状态</button></div>
        <div class="admin-metrics"><div class="mini-stat"><span>正在使用</span><strong>{{ totals.in_use }}</strong></div><div class="mini-stat"><span>空闲连接</span><strong>{{ totals.idle }}</strong></div><div class="mini-stat"><span>等待连接</span><strong>{{ totals.waiting }}</strong></div><div class="mini-stat"><span>等待超时累计</span><strong>{{ totals.timeouts }}</strong></div></div>
        <p class="hint">汇总最近 60 秒内有活动的 Web 与调度进程；计数随进程重启重置。业务任务连接单独计数。</p>
        <div class="pool-processes"><p v-for="process in state.diagnostics?.processes || []" :key="process.pid">{{ process.role==='scheduler'?'调度服务':'Web 服务' }} · {{ process.pid }} · {{ process.pools.reduce((n,p)=>n+p.in_use,0) }} 个连接使用中 / 上限 {{ process.pools.reduce((n,p)=>n+p.limit,0) }}</p></div>
        <p class="hint">连接等待 P95：{{ state.diagnostics?.metrics?.['database:pool_wait']?.p95_ms ?? '—' }} ms · 建立连接 P95：{{ state.diagnostics?.metrics?.['database:connect']?.p95_ms ?? '—' }} ms</p>
      </section>
    </template>
  </section>
</template>
<script setup>
import {computed,nextTick,onMounted,onBeforeUnmount,ref} from 'vue';
import {api} from '../api';
import LoadingStatus from './LoadingStatus.vue';
import NacosBindingFields from './NacosBindingFields.vue';
import DatabaseUsageExamples from './DatabaseUsageExamples.vue';
import {useUnsavedChanges} from '../composables/useUnsavedChanges';
const props=defineProps({confirm:Function});
const state=ref({}),form=ref({}),loading=ref(false),busy=ref(''),error=ref(''),message=ref(''),hostInput=ref(null),nacosLoading=ref(false);
const sourceLabels={direct:'自定义连接',service:'服务配置 / Nacos',nacos:'Nacos 配置'};
// 权限由后端根据内置管理员身份返回，未知时默认只读；接口仍会再次鉴权。
const canEdit=computed(()=>state.value.can_edit===true);
const {saved}=useUnsavedChanges(()=>form.value,()=>canEdit.value && form.value.revision!=null);
const poolFields=[{key:'web_pool_size',label:'每个 Web 进程的池内上限',min:1,max:32},{key:'web_max_overflow',label:'每个 Web 进程的额外连接',min:0,max:32},{key:'scheduler_pool_size',label:'调度进程的池内上限',min:1,max:64},{key:'scheduler_max_overflow',label:'调度进程的额外连接',min:0,max:32},{key:'pool_timeout',label:'等待空闲连接（秒）',min:1,max:120},{key:'pool_recycle',label:'连接回收周期（秒）',min:30,max:3600},{key:'connect_timeout',label:'建立连接超时（秒）',min:1,max:60},{key:'query_timeout',label:'平台查询超时（秒）',min:1,max:3600}];
const capacity=computed(()=>2*(Number(form.value.web_pool_size||0)+Number(form.value.web_max_overflow||0))+Number(form.value.scheduler_pool_size||0)+Number(form.value.scheduler_max_overflow||0));
const totals=computed(()=>{const sum={in_use:0,idle:0,waiting:0,timeouts:0};for(const process of state.value.diagnostics?.processes || [])for(const pool of process.pools)for(const key of Object.keys(sum))sum[key]+=pool[key]||0;return sum;});
let generation=0;
async function customize(){if(!canEdit.value || loading.value || busy.value)return;form.value.source='direct';await nextTick();hostInput.value?.focus();}
// 运行状态刷新不能覆盖编辑中的草稿；只有首次加载/保存后才替换 form 并更新基线。
// generation 同时过滤晚到响应与卸载后的回写，密码始终用空输入表示保留已有密文。
async function load(assign=true){const seq=++generation;loading.value=true;error.value='';try{const data=await api.platformDatabase();if(seq!==generation)return;state.value=data;if(assign){form.value={...data.saved,nacos:data.saved.nacos||{},nacos_md5:'',nacos_settings_token:'',password:''};saved();}}catch(e){if(seq===generation)error.value=e.message;}finally{if(seq===generation)loading.value=false;}}
function invalidateNacos(){form.value.nacos_md5='';form.value.nacos_settings_token='';form.value.password='';if(form.value.source==='nacos')form.value.password_set=false;}
function loadNacos(result){const value=result.profile||{};for(const key of ['host','port','database','schema','user','password_set'])if(key in value)form.value[key]=value[key];form.value.password='';form.value.nacos=result.binding||form.value.nacos;form.value.nacos_md5=result.md5;form.value.nacos_settings_token=result.nacos_settings_token;message.value='已读取 Nacos 配置，可编辑后测试或保存待重启配置。';error.value='';}
// 保存只生成待重启配置，不进行热切库；回读服务端版本，保留当前生效与待生效的区分。
async function run(action){if(!canEdit.value || busy.value || loading.value || nacosLoading.value)return;const nacos=form.value.source==='nacos';if(nacos && !form.value.nacos_md5){error.value='请先读取 Nacos 配置，再测试或保存。';return;}if(action==='save'&&!await props.confirm({title:'保存平台连接配置？',message:(nacos?'测试通过后将同步修改 Nacos JSON，其他消费者也会读到修改。':'')+'保存为待重启配置。更换数据库需要先完成数据迁移，再完整重启平台服务。',confirmText:'测试并保存',danger:true}))return;busy.value=action;error.value='';message.value='';try{const result=await api.changePlatformDatabase(action,form.value);if(action==='save'){await load();message.value=result.nacos_synced?'平台配置已同步至 Nacos 并加密保存，完整重启服务后生效。':'平台配置已加密保存，完整重启服务后生效。';}else message.value=`平台连接及结构检查通过，耗时 ${result.elapsed_ms} ms。`;}catch(e){error.value=e.message;}finally{busy.value='';}}
onMounted(load);onBeforeUnmount(()=>generation++);
</script>
<style scoped>
.platform-database,.platform-database .surface-card,.platform-database fieldset{display:grid;gap:16px;min-width:0}.platform-database fieldset{border:0;padding:0;margin:0}.platform-database h3,.platform-database p{margin:0;overflow-wrap:anywhere}.platform-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr));gap:16px}.platform-database label{display:grid;gap:8px;align-content:start}.platform-heading{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.pool-processes{display:grid;gap:6px}.platform-database .filter-actions{flex-wrap:wrap}
.platform-database .disclosure>.hint{padding:0 16px 16px}
</style>
