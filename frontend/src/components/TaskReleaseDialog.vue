<template>
  <ModalShell :embedded="embedded" :open="Boolean(pid)" label="任务代码版本" panel-class="task-release-modal" @close="close">
    <header class="modal-head release-top"><div><h3>{{ record?.task_name || candidate?.task_name || pid }}</h3><p class="hint">当前版本 <strong>{{ short(record?.active_version) }}</strong> → 所选版本 <strong>{{ short(preview?.release.version) }}</strong></p></div><div class="filter-actions">
      <button v-if="canPrepare" class="btn primary" :disabled="busy || !entry" @click="prepare">识别并安装依赖</button>
      <button v-else-if="canPublish && !blockedChecks.length" class="btn primary" :disabled="busy" @click="publish">{{ preview.release.published_at ? '回滚到此版本' : '发布此版本' }}</button>
      <span v-else-if="preview?.release.status === 'preparing'" class="tag warning">{{ preview.release.prepare_stage || '正在准备依赖…' }}</span>
      <button v-else-if="blockedChecks.length" class="btn warning" @click="jump(checklist)">查看阻止项（{{ blockedChecks.length }}）</button>
      <button v-if="!embedded" class="btn" :disabled="busy" @click="close">关闭</button>
    </div></header>
    <div class="modal-body release-body">
      <LoadingStatus :active="loading || busy" :label="busyLabel || '正在读取任务版本…'" />
      <div v-if="error" class="inline-alert danger" role="alert">{{ error }}</div><p v-if="message" class="inline-alert success" role="status">{{ message }}</p>
      <section v-if="preview" ref="checklist" tabindex="-1" class="surface-card release-check-summary" aria-label="发布检查摘要">
        <h4>发布检查摘要</h4><div class="release-check-groups">
          <div v-for="group in checkGroups" :key="group.key" :class="['release-check-group',group.key]"><strong>{{ group.label }} · {{ group.items.length }}</strong><ul v-if="group.items.length"><li v-for="item in group.items" :key="item.label"><span>{{ item.label }}：{{ item.message }}</span><button v-if="item.target && group.key!=='passed'" class="btn" @click="jump(item.target==='entry'?entryField:item.target==='trial'?trialSettings:gatesPanel)">{{ item.action }}</button></li></ul><p v-else class="hint">无</p></div>
        </div>
        <p class="hint">{{ scheduleImpact }}。已排队或运行中的执行继续使用原版本。</p>
      </section>
      <section v-if="candidate" class="surface-card release-candidate" :class="candidate.kind"><span class="tag" :class="candidate.kind === 'delete' ? 'danger' : candidate.kind === 'new' ? 'success' : 'warning'">{{ {new:'新任务待发布',update:'有更新待发布',delete:'GitLab 已删除',recover:'原任务待恢复关联'}[candidate.kind] }}</span><p class="mono">{{ candidate.path }} @ {{ candidate.sha.slice(0, 8) }}</p><p v-if="candidate.error" class="danger-text">{{ candidate.error }}</p><p v-if="candidate.kind === 'delete'" class="hint">确认后停止后续调度，任务移入回收站。历史版本、运行日志和输出文件保留；已排队或运行的实例继续完成。</p><div v-if="!['delete','recover'].includes(candidate.kind)" class="gitlab-task-configuration">
        <label>任务标识（自动生成）<input class="input mono" :value="candidate.pid" readonly /></label>
        <p class="hint">任务标识由平台生成且不可修改。无需 .wfs-task.json；名称与入口在此配置。</p><p v-if="candidate.kind==='update'" class="hint">已有调度配置中的名称与入口优先；如需调整，请到任务配置页修改。</p>
        <label>发布任务名称<input class="input" v-model.trim="taskName" maxlength="200" :disabled="busy" /></label>
        <label>发布 Python 入口<select class="select" v-model="sourceEntry" :disabled="busy"><option value="" disabled>请选择 Python 入口</option><option v-for="file in candidate.main_file_options" :key="file" :value="file">{{ file }}</option></select></label>
      </div><p v-if="candidate.recovery" class="hint">保留原任务编号 {{ candidate.recovery.pid }}、调度配置及历史记录。恢复后先重新获取代码并检查依赖，再发布和启用调度。</p><div class="filter-actions"><button v-if="candidate.kind === 'recover'" class="btn primary" :disabled="busy || candidate.blocked" @click="recoverIdentity">确认恢复原任务</button><button v-else-if="candidate.kind === 'delete'" class="btn danger" :disabled="busy || candidate.blocked" @click="remove">确认删除任务</button><button v-else class="btn primary" :disabled="busy || candidate.blocked || !taskName || !sourceEntry" @click="stage">{{ preview?.release.git_source?.sha === candidate.sha ? '重新获取 GitLab 版本' : '获取 GitLab 版本并查看差异' }}</button></div></section>
      <div v-if="record" class="release-overview"><span class="tag info">{{ record.deleted_at ? '回收站' : record.active_version ? '当前版本 ' + short(record.active_version) : '尚未发布' }}</span><span class="hint">{{ record.group_name }} / {{ record.folder_name }}</span><button v-if="record.deleted_at" class="btn" :disabled="busy" @click="restore">恢复任务（暂停）</button></div>
      <section v-if="versions.length" class="release-history" aria-label="代码版本历史"><button v-for="version in versions" :key="version.version" class="btn" :class="preview?.release.version === version.version ? 'primary' : ''" :disabled="busy" @click="selectVersion(version.version)">{{ short(version.version) }} · {{ label(version.status) }}</button></section>
      <section v-if="preview" class="surface-card release-preview" aria-label="发布版本预览">
        <h3>版本 {{ short(preview.release.version) }}</h3><p class="hint">新增 {{ counts.added }} · 修改 {{ counts.modified }} · 删除 {{ counts.deleted }} 个文件</p>
        <p v-if="preview.release.task_name">发布任务名称：{{ preview.release.task_name }}</p><p v-if="preview.release.git_source" class="mono">GitLab 提交 {{ preview.release.git_source.sha }}</p><p class="hint">{{ preview.release.message || '先核对文件差异，再检查依赖并确认发布。' }}</p>
        <div ref="entryField" tabindex="-1" class="form-row"><label for="release-entry">Python 入口</label><select id="release-entry" v-model="entry" class="select" :disabled="busy || !['staged','failed'].includes(preview.release.status)"><option v-for="file in preview.release.manifest.filter(f => f.path.endsWith('.py'))" :key="file.path" :value="file.path">{{ file.path }}</option></select></div>
        <section class="release-dependencies" aria-label="任务依赖">
          <h4>运行依赖</h4>
          <p>{{ dependencySource }}：{{ preview.release.requirements?.join('，') || '未识别到第三方依赖' }}</p>
          <p class="hint">无需上传 requirements.txt；平台识别代码及引用的公共模块依赖。启用 Nexus 后可在线安装并锁定版本，已提供的依赖清单优先使用。检查期间不会运行任务。</p>
          <details v-if="preview.release.dependency_report?.modules?.length" class="disclosure"><summary>查看识别依据</summary><ul><li v-for="item in preview.release.dependency_report.modules" :key="item.module"><code>{{ item.module }}</code> → {{ item.package }}<span class="hint"> · {{ item.sources.join('、') }}</span></li></ul></details>
          <p v-for="warning in preview.release.dependency_report?.warnings || []" :key="warning" class="hint">{{ warning }}</p>
          <details v-if="canPrepare" class="disclosure"><summary>补充或调整依赖（可选）</summary><div class="disclosure-body">
            <label class="release-reason" for="release-dependencies">本版本完整依赖清单<textarea id="release-dependencies" v-model="dependencyText" class="input mono" rows="5" :disabled="busy" placeholder="requests&#10;pandas&#10;例如：openpyxl>=3.1" /></label>
            <p class="hint">每行一个包名，可指定版本。动态导入、可选功能或包名不同的情况可在此补充；点击“识别并安装依赖”后保存。只影响本版本，无需修改 GitLab 代码。</p>
          </div></details>
          <button v-if="canRebuild" class="btn" :disabled="busy" @click="rebuild">用原代码重新准备依赖</button>
          <p v-if="canRebuild" class="hint">执行时缺包可使用此入口。新建候选版本，检查通过并发布后生效。</p>
          <details v-if="preview.release.installed_dependencies?.length" class="disclosure"><summary>已安装并锁定 {{ preview.release.installed_dependencies.length }} 个包</summary><p class="mono">{{ preview.release.installed_dependencies.map(item=>`${item.name}==${item.version}`).join('，') }}</p></details>
        </section>
        <section v-if="preview.preflight" class="release-checklist" aria-label="发布前检查">
          <h4>发布前检查</h4>
          <p>当前 {{ short(preview.preflight.current_version) }} → 候选 {{ short(preview.preflight.candidate_version) }}</p>
          <p>入口 {{ preview.preflight.entry }} · {{ preview.preflight.entry_present ? '文件存在' : '缺少入口，不能发布' }}</p>
          <p>依赖{{ preview.preflight.dependencies_changed ? '有变更，请重点核对' : '未变更' }} · 环境{{ preview.preflight.environment_ready ? '检查通过' : '待检查' }}</p>
          <p>公共 SDK：{{ preview.preflight.shared_sdk_changed ? '有版本变化，请核对兼容性' : '未检测到版本变化' }}</p><p class="hint mono">候选 SDK {{ preview.preflight.shared_sdk_candidate || '历史版本未记录' }}</p>
          <p>活动实例 {{ preview.preflight.active_instances }} · 调度{{ preview.preflight.schedule_enabled ? '保持启用' : '保持暂停 / 未配置' }}</p>
          <p class="hint">检查通过代表语法和依赖可用，业务逻辑仍需验证。发布不替换已排队或运行中的版本。</p>
        </section>
        <section v-if="preview.gates" ref="gatesPanel" tabindex="-1" class="surface-card release-gates"><h4>发布门禁 · {{ preview.gates.environment }}</h4><button class="btn" :disabled="busy" @click="work('正在刷新发布检查…',()=>inspect(preview.release.version))">刷新发布检查</button><p>发布窗口：{{ preview.gates.window_open ? '允许发布' : '当前窗口外' }}</p><p>试运行：{{ preview.gates.trial.passed ? '已有成功记录' : '尚无成功记录' }}{{ preview.gates.require_trial ? '（发布必需）' : '（可选）' }}</p><button v-if="allowOperations && ['ready','applied'].includes(preview.release.status)" class="btn" :disabled="busy" @click="trial">使用测试连接试运行此版本</button><p class="hint">试运行不会自动发布。请在任务的运行策略中配置测试连接，查看执行结果后再决定是否上线。</p></section>
        <label class="release-reason">本次发布说明<input v-model="publishReason" class="input" maxlength="500" placeholder="说明本次变更与验证结果"></label>
        <p class="hint">版本创建：{{ preview.release.actor }} · {{ preview.release.created_at }}<template v-if="preview.release.published_at">；最近发布：{{ preview.release.published_by || '历史记录' }} · {{ preview.release.published_at }} · {{ preview.release.publish_reason || '未填写说明' }}</template></p>
        <label class="checkbox-row"><input v-model="changedOnly" type="checkbox">仅显示变更文件</label>
        <div class="release-diff"><div class="release-files" aria-label="发布文件清单"><button v-for="file in files" :key="file.path" class="btn" :class="path === file.path ? 'primary' : ''" @click="inspectFile(file.path)">{{ {added:'新增',modified:'修改',deleted:'删除'}[file.kind] || '未修改' }} {{ file.path }}</button></div><div class="release-code"><p class="mono">{{ path || '选择文件查看差异' }}</p><LoadingStatus :active="diffLoading" label="正在读取差异…" /><pre class="log-pre" tabindex="0">{{ diff || '从左侧选择文件。' }}</pre></div></div>
      </section>
      <details v-if="allowOperations && record && !record.deleted_at" ref="trialSettings" class="disclosure"><summary>试运行设置与执行请求</summary><div class="disclosure-body"><TaskOperations :pid="pid" :published="Boolean(record.active_version)" :confirm="confirm" @execution="$emit('execution',$event)" /></div></details>
      <p v-if="!loading && !candidate && !versions.length" class="hint">没有可用代码版本。请配置 GitLab 并完成检查。</p>
    </div>
  </ModalShell>
</template>
<script setup>
import { computed, ref, watch, onBeforeUnmount, defineAsyncComponent } from 'vue';
import {useRefreshLoop} from '../composables/useRefreshLoop.js';
import { api } from '../api';
import {confirmUnsaved,useUnsavedChanges} from '../composables/useUnsavedChanges';
import ModalShell from './ModalShell.vue';
import LoadingStatus from './LoadingStatus.vue';
const TaskOperations=defineAsyncComponent(()=>import('./TaskOperations.vue'));
const props = defineProps({ allowOperations:Boolean, embedded: Boolean, pid: { type: String, default: '' }, confirm: { type: Function, required: true } });
const emit = defineEmits(['close', 'changed', 'execution']);
const record = ref(null), candidate = ref(null), versions = ref([]), preview = ref(null), entry = ref('');
const loading = ref(false), busy = ref(false), busyLabel = ref(''), error = ref(''), message = ref('');
const path = ref(''), diff = ref(''), diffLoading = ref(false);
let generation = 0, alive = true, diffSequence = 0, previewSequence = 0;
const short = value => value?.slice(0, 8) || '—';
const label = value => ({ staged:'待检查', preparing:'检查中', ready:'检查通过', applied:'已发布', failed:'检查失败',cleaned:'已清理' }[value] || value);
const counts = computed(() => Object.fromEntries(['added','modified','deleted'].map(kind => [kind, preview.value?.changes.filter(f => f.kind === kind).length || 0])));
const publishReason=ref('');
const changedOnly = ref(true);
const files = computed(() => { const changes = new Map((preview.value?.changes || []).map(f => [f.path, f.kind])); return [...new Set([...(preview.value?.release.manifest || []).map(f => f.path), ...changes.keys()])].sort().map(path => ({path,kind:changes.get(path)})).filter(file => !changedOnly.value || file.kind); });
const canPublish = computed(() => preview.value && !record.value?.deleted_at && ['ready','applied'].includes(preview.value.release.status) && record.value?.active_version !== preview.value.release.version && preview.value.preflight?.entry_present !== false);
const canPrepare=computed(()=>['staged','failed'].includes(preview.value?.release.status) && !record.value?.deleted_at);
const canRebuild=computed(()=>['ready','applied'].includes(preview.value?.release.status) && record.value && !record.value.deleted_at && !record.value.pending);
const dependencySource=computed(()=>({auto:'自动识别',file:'requirements.txt',manual:'页面配置'}[preview.value?.release.requirements_source] || '原版本依赖'));
const dependencyText=ref('');
let dependencyVersion='';
const dependencyForm=useUnsavedChanges(()=>dependencyText.value,()=>Boolean(canPrepare.value && !loading.value));
const checklist=ref(null),entryField=ref(null),gatesPanel=ref(null),trialSettings=ref(null);
function jump(element){if(!element)return;if(element.tagName==='DETAILS')element.open=true;(element.tagName==='DETAILS'?element.querySelector('summary'):element)?.focus({preventScroll:true});element.scrollIntoView({block:'nearest'});}
const checks=computed(()=>{
  const p=preview.value?.preflight,g=preview.value?.gates;
  if(!preview.value)return [];
  const items=[];
  if(p){items.push({label:'任务入口',state:p.entry_present?'passed':'blocked',message:p.entry_present?p.entry:'缺少调度使用的入口文件',target:'entry',action:'查看入口'});items.push({label:'依赖环境',state:p.environment_ready?'passed':'pending',message:p.environment_ready?'检查通过':'请完成依赖环境检查',target:'entry',action:'查看依赖'});}
  if(g){
    items.push({label:'发布窗口',state:g.window_open?'passed':'blocked',message:g.window_open?'允许发布':'请等待允许发布的时间段',target:'gates',action:'查看发布窗口'});
    if(g.require_trial)items.push({label:'候选版本试运行',state:g.trial?.passed?'passed':'blocked',message:g.trial?.passed?'已有成功记录':'需要同一版本的成功试运行',target:allowTrialSettings.value?'trial':'gates',action:allowTrialSettings.value?'打开试运行设置':'查看试运行条件'});
  }
  return items;
});
const allowTrialSettings=computed(()=>props.allowOperations && record.value && !record.value.deleted_at);
const blockedChecks=computed(()=>checks.value.filter(item=>item.state==='blocked'));
const checkGroups=computed(()=>[['blocked','阻止发布'],['pending','待完成'],['passed','已通过']].map(([key,label])=>({key,label,items:checks.value.filter(item=>item.state===key)})));
const scheduleImpact = computed(() => {
  const plan = preview.value?.preflight;
  if (!plan?.schedule_enabled) return '自动调度保持暂停或未配置';
  if (plan.next_run_time) return `下次计划执行时间为 ${plan.next_run_time}`;
  return '自动调度保持启用，暂无下次执行时间';
});
async function close() { if (!busy.value && await confirmUnsaved(props.confirm)) emit('close'); }
function changed() { emit('changed'); window.dispatchEvent(new Event('wfs:task-releases-refresh')); }
const taskName=ref(''),sourceEntry=ref('');
const publicationForm=useUnsavedChanges(()=>({taskName:taskName.value,main_file:sourceEntry.value}),()=>Boolean(candidate.value && !['delete','recover'].includes(candidate.value.kind) && !loading.value));
let configurationId='';
async function refresh() {
  const token = generation, pid = props.pid;
  const [state, detail] = await Promise.all([api.gitlabTasks(), api.packages(pid)]);
  if (!alive || token !== generation) return;
  candidate.value = state.items.find(i => i.pid === pid) || null;
  if(configurationId!==candidate.value?.id){configurationId=candidate.value?.id || '';taskName.value=candidate.value?.task_name || '';sourceEntry.value=candidate.value?.main_file || '';publicationForm.saved();}
  record.value = detail.task || null;
  versions.value = detail.versions || [];
}
async function inspect(version, resetDependencies=false) {
  if (!version) return; const token = generation, request = ++previewSequence; diffSequence++; path.value = ''; diff.value = ''; diffLoading.value = false;
  const data = await api.packagePreview(props.pid, version);
  if (!alive || token !== generation || request !== previewSequence) return;
  const reset = resetDependencies || dependencyVersion!==version || !dependencyForm.dirty.value;
  preview.value = data; entry.value = data.release.main_file;
  if(reset){dependencyVersion=version;dependencyText.value=(data.release.requirements || []).join('\n');dependencyForm.saved();}

}
async function selectVersion(version){if(version!==preview.value?.release.version && dependencyForm.dirty.value && !await confirmUnsaved(props.confirm))return;await work('正在读取代码版本…',()=>inspect(version));}
async function work(text, action) {
  if (busy.value) return; const token = generation; busy.value = true; busyLabel.value = text; error.value = '';
  try { await action(); } catch (err) { if (alive && token === generation) error.value = err.message; return false; }
  finally { if (alive && token === generation) { busy.value = false; busyLabel.value = ''; } }
}
async function inspectFile(filename) {
  const token = generation, request = ++diffSequence; path.value = filename; diffLoading.value = true;
  try { const data = await api.packagePreview(props.pid, preview.value.release.version, filename); if (alive && token === generation && request === diffSequence) diff.value = data.diff || data.content || '文件为空或没有变更。'; }
  catch (err) { if (alive && token === generation && request === diffSequence) error.value = err.message; }
  finally { if (alive && token === generation && request === diffSequence) diffLoading.value = false; }
}
async function stage() { await work('正在获取并校验 GitLab 代码…', async () => { const data = await api.gitlabTaskAction({action:'stage', id:candidate.value.id, configuration:{task_name:taskName.value, main_file:sourceEntry.value}}); await refresh(); await inspect(data.version); changed(); }); }
async function prepare() { await work('正在识别并安装任务依赖…', async () => { const token=generation,fields={action:'prepare',pid:props.pid,version:preview.value.release.version,main_file:entry.value};if(dependencyForm.dirty.value)fields.requirements=dependencyText.value;await api.packageAction(fields);if(!alive || token!==generation)return;dependencyForm.saved();await inspect(fields.version,true); }); }
async function rebuild() { await work('正在用原代码创建候选版本…', async () => { const token=generation;const data=await api.packageAction({action:'rebuild',pid:props.pid,version:preview.value.release.version,revision:record.value.revision});if(!alive || token!==generation)return;await refresh();if(!alive || token!==generation)return;await inspect(data.version);message.value='已使用原代码创建候选版本。核对依赖后点击“识别并安装依赖”，通过后再发布。';changed(); }); }
async function publish() {
  if(!canPublish.value || blockedChecks.value.length)return;
  const { version, published_at: publishedAt } = preview.value.release;
  const { revision } = record.value;
  const taskName = preview.value.release.task_name || record.value.task_name;
  const pid = props.pid;
  const rollback = Boolean(publishedAt);
  if (!await props.confirm({title:rollback ? '回滚任务代码' : '发布任务代码',message:`确认${rollback ? '回滚' : '发布'} ${taskName}？`,details:[`所选版本 ${short(version)}。${scheduleImpact.value}。`,'新的执行使用所选版本。已排队或运行的实例继续使用原版本。','保留调度配置、历史版本和业务输出。'],confirmText:rollback ? '确认回滚' : '确认发布',danger:rollback})) return;
  if (pid !== props.pid || version !== preview.value?.release.version) return;
  await work('正在发布并等待调度器确认…', async () => { await api.packageAction({action:rollback ? 'rollback' : 'publish',pid,version,revision,reason:publishReason.value}); await refresh(); await inspect(version); message.value = rollback ? '代码已回滚。' : '任务代码已发布。'; changed(); });
}
async function trial(){if(!await props.confirm({title:'试运行候选版本',message:'此操作会执行候选代码，只提供运行策略中配置的测试连接。',details:['请先确认脚本不会自行连接生产系统或产生外部副作用。','试运行结果单独记录，不替换当前发布版本。'],confirmText:'提交试运行',danger:true}))return;await work('正在提交试运行…',async()=>{await api.submitExecutionRequest(props.pid,{kind:'trial',context:{version:preview.value.release.version}});message.value='试运行请求已保存，可在下方“试运行设置与执行请求”中刷新结果。';});}
async function remove() {
  if (!await props.confirm({title:'确认删除任务',message:`GitLab 已删除 ${candidate.value.task_name}，确认停止后续调度并移入回收站？`,details:['代码历史、日志和输出文件保留，不清理运行中的目录。','已排队或运行的实例继续完成。'],confirmText:'确认删除',danger:true})) return;
  await work('正在删除任务…', async () => { await api.gitlabTaskAction({action:'delete',id:candidate.value.id}); await refresh(); message.value = '任务已移入回收站，输出文件已保留。'; changed(); });
}
async function recoverIdentity() {
  const item=candidate.value;
  if(!item?.recovery || !await props.confirm({title:'恢复原任务',message:`将 ${item.path} 重新关联到原任务 ${item.recovery.pid}？`,details:['保留原任务编号、调度配置、历史版本、日志和输出。','自动调度先暂停。恢复关联后重新获取代码、检查依赖并发布，再手动启用调度。'],confirmText:'确认恢复关联'}))return;
  await work('正在恢复原任务关联…',async()=>{
    await api.gitlabTaskAction({action:'recover',id:item.id});
    changed();
    await api.scanGitlab();
    emit('close');
  });
}
async function restore() { await work('正在恢复任务…', async () => { await api.packageAction({action:'restore',pid:props.pid,revision:record.value.revision,reason:publishReason.value}); await refresh(); message.value = '任务已恢复，自动调度保持暂停。'; changed(); }); }
watch(() => props.pid, async pid => {
  const token = ++generation; diffSequence++; record.value = null; candidate.value = null; versions.value = []; preview.value = null; error.value = ''; message.value = ''; path.value = ''; diff.value = ''; diffLoading.value = false; busy.value = false;
  if (!pid) return; loading.value = true;
  try { await refresh(); if (token === generation && versions.value.length) await inspect(versions.value[0].version); }
  catch (err) { if (alive && token === generation) error.value = err.message; return false; }
  finally { if (alive && token === generation) loading.value = false; }
}, { immediate:true });
useRefreshLoop({load:()=>work('正在读取依赖检查结果…',async()=>{await inspect(preview.value?.release.version);await refresh();}),enabled:()=>Boolean(props.pid && preview.value?.release.status==='preparing'),interval:2000,immediate:false});
onBeforeUnmount(() => { alive = false; generation++; });
</script>
<style>
.gitlab-task-configuration{display:grid;gap:12px;margin:16px 0;min-width:0}.gitlab-task-configuration label{display:grid;gap:8px;min-width:0}
.release-top .filter-actions { flex-wrap: wrap; justify-content: flex-end; }
.release-check-summary h4 { margin: 0 0 12px; }
.release-check-groups { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(185px, 100%), 1fr)); gap: 12px; }
.release-check-group { border: 1px solid var(--line); border-radius: 10px; padding: 12px; min-width: 0; }
.release-check-group.blocked > strong { color: var(--danger); }
.release-check-group.pending > strong { color: var(--warning); }
.release-check-group.passed > strong { color: var(--success); }
.release-check-group ul { padding-left: 16px; margin: 0; }
.release-check-group li { overflow-wrap: anywhere; margin-top: 8px; }
.release-check-group .btn { display: flex; margin-top: 5px; }
.task-release-modal{width:min(1200px,96vw)!important}.release-body{display:grid;gap:20px;overflow-wrap:anywhere}.release-body .surface-card{min-width:0}.release-candidate>p{margin:14px 0;overflow-wrap:anywhere}.release-candidate.delete{border-color:#a05858}.release-overview,.release-history{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.release-history{max-height:150px;overflow:auto}.release-diff{display:grid;grid-template-columns:minmax(170px,30%) minmax(0,1fr);gap:20px}.release-files{display:grid;gap:8px;align-content:start;max-height:500px;overflow:auto}.release-files .btn{text-align:left;overflow-wrap:anywhere;white-space:normal}.release-code{min-width:0}.release-code>p{margin-bottom:12px;overflow-wrap:anywhere}.release-code pre{min-height:220px;max-height:480px;white-space:pre;overflow:auto;font-size:12px}@media(max-width:720px){.release-diff{grid-template-columns:1fr}.release-files{max-height:200px}}
.release-preview { display: grid; gap: 16px; align-content: start; }
.release-preview > h3, .release-preview > p { margin: 0; }
.release-reason { display: grid; gap: 8px; min-width: 0; }
.release-dependencies { display:grid; gap:12px; min-width:0; padding:16px; border:1px solid var(--line); border-radius:10px; }
.release-dependencies > h4,.release-dependencies > p { margin:0; }
.release-dependencies > .btn { justify-self:start; }
.release-dependencies textarea { width:100%; resize:vertical; min-height:110px; }
.release-dependencies ul { padding-left:20px; }
.release-dependencies li { margin:8px 0; overflow-wrap:anywhere; }
.release-checklist, .release-gates { display: grid; gap: 12px; min-width: 0; }
.release-checklist > h4, .release-checklist > p,
.release-gates > h4, .release-gates > p { margin: 0; }
.release-gates > .btn, .release-preview > .checkbox-row { justify-self: start; }
</style>
