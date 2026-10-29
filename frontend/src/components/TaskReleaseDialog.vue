<template>
  <ModalShell :embedded="embedded" :open="Boolean(pid)" label="任务代码版本" panel-class="task-release-modal" @close="close">
    <header class="modal-head"><div><h3>{{ record?.task_name || candidate?.task_name || pid }}</h3><p class="hint">GitLab 代码审查与任务版本</p></div><button v-if="!embedded" class="btn" :disabled="busy" @click="close">关闭</button></header>
    <div class="modal-body release-body">
      <LoadingStatus :active="loading || busy" :label="busyLabel || '正在读取任务版本…'" />
      <div v-if="error" class="inline-alert danger" role="alert">{{ error }}</div><p v-if="message" class="inline-alert success" role="status">{{ message }}</p>
      <section v-if="candidate" class="surface-card release-candidate" :class="candidate.kind"><span class="tag" :class="candidate.kind === 'delete' ? 'danger' : candidate.kind === 'new' ? 'success' : 'warning'">{{ {new:'新任务待发布',update:'有更新待发布',delete:'GitLab 已删除'}[candidate.kind] }}</span><p class="mono">{{ candidate.path }} @ {{ candidate.sha.slice(0, 8) }}</p><p v-if="candidate.error" class="danger-text">{{ candidate.error }}</p><p v-if="candidate.kind === 'delete'" class="hint">确认后停止后续调度，任务移入回收站。历史版本、运行日志和输出文件保留；已排队或运行的实例继续完成。</p><div class="filter-actions"><button v-if="candidate.kind === 'delete'" class="btn danger" :disabled="busy || candidate.blocked" @click="remove">确认删除任务</button><button v-else class="btn primary" :disabled="busy || candidate.blocked" @click="stage">{{ preview?.release.git_source?.sha === candidate.sha ? '重新获取 GitLab 版本' : '获取 GitLab 版本并查看差异' }}</button></div></section>
      <div v-if="record" class="release-overview"><span class="tag info">{{ record.deleted_at ? '回收站' : record.active_version ? '当前版本 ' + short(record.active_version) : '尚未发布' }}</span><span class="hint">{{ record.group_name }} / {{ record.folder_name }}</span><button v-if="record.deleted_at" class="btn" :disabled="busy" @click="restore">恢复任务（暂停）</button></div>
      <section v-if="versions.length" class="release-history" aria-label="代码版本历史"><button v-for="version in versions" :key="version.version" class="btn" :class="preview?.release.version === version.version ? 'primary' : ''" :disabled="busy" @click="work('正在读取代码版本…', () => inspect(version.version))">{{ short(version.version) }} · {{ label(version.status) }}</button></section>
      <section v-if="preview" class="surface-card release-preview" aria-label="发布版本预览">
        <h3>版本 {{ short(preview.release.version) }}</h3><p class="hint">新增 {{ counts.added }} · 修改 {{ counts.modified }} · 删除 {{ counts.deleted }} 个文件</p>
        <p v-if="preview.release.git_source" class="mono">GitLab 提交 {{ preview.release.git_source.sha }}</p><p class="hint">{{ preview.release.message || '先核对文件差异，再检查依赖并确认发布。' }}</p>
        <div class="form-row"><label for="release-entry">Python 入口</label><select id="release-entry" v-model="entry" class="select" :disabled="busy || !['staged','failed'].includes(preview.release.status)"><option v-for="file in preview.release.manifest.filter(f => f.path.endsWith('.py'))" :key="file.path" :value="file.path">{{ file.path }}</option></select></div>
        <p class="hint">依赖：{{ preview.release.requirements.join('，') || 'Python 标准库' }}。独立环境检查通过后才能发布；不会在检查期间运行任务。</p>
        <div class="filter-actions"><button v-if="['staged','failed'].includes(preview.release.status) && !record?.deleted_at" class="btn primary" :disabled="busy || !entry" @click="prepare">检查依赖环境</button><span v-if="preview.release.status === 'preparing'" class="tag warning">{{ preview.release.prepare_stage || '正在准备依赖…' }}</span><button v-if="canPublish" class="btn primary" :disabled="busy" @click="publish">{{ preview.release.published_at ? '回滚到此版本' : '发布此版本' }}</button></div>
        <section v-if="preview.preflight" class="release-checklist" aria-label="发布前检查">
          <h4>发布前检查</h4>
          <p>当前 {{ short(preview.preflight.current_version) }} → 候选 {{ short(preview.preflight.candidate_version) }}</p>
          <p>入口 {{ preview.preflight.entry }} · {{ preview.preflight.entry_present ? '文件存在' : '缺少入口，不能发布' }}</p>
          <p>依赖{{ preview.preflight.dependencies_changed ? '有变更，请重点核对' : '未变更' }} · 环境{{ preview.preflight.environment_ready ? '检查通过' : '待检查' }}</p>
          <p>公共 SDK：{{ preview.preflight.shared_sdk_changed ? '有版本变化，请核对兼容性' : '未检测到版本变化' }}</p><p class="hint mono">候选 SDK {{ preview.preflight.shared_sdk_candidate || '历史版本未记录' }}</p>
          <p>活动实例 {{ preview.preflight.active_instances }} · 调度{{ preview.preflight.schedule_enabled ? '保持启用' : '保持暂停 / 未配置' }}</p>
          <p class="hint">检查通过代表语法和依赖可用，业务逻辑仍需验证。发布不替换已排队或运行中的版本。</p>
        </section>
        <section v-if="preview.gates" class="surface-card"><h4>发布门禁 · {{ preview.gates.environment }}</h4><button class="btn" :disabled="busy" @click="work('正在刷新发布检查…',()=>inspect(preview.release.version))">刷新发布检查</button><p>发布窗口：{{ preview.gates.window_open ? '允许发布' : '当前窗口外' }}</p><p>CI：{{ preview.gates.ci.message }} · {{ preview.gates.ci.status }}</p><p>试运行：{{ preview.gates.trial.passed ? '已有成功记录' : '尚无成功记录' }}{{ preview.gates.require_trial ? '（发布必需）' : '（可选）' }}</p><button v-if="allowOperations && ['ready','applied'].includes(preview.release.status)" class="btn" :disabled="busy" @click="trial">使用测试连接试运行此版本</button><p class="hint">试运行不会自动发布。请在任务的运行策略中配置测试连接，查看执行结果后再决定是否上线。</p></section>
        <label>本次发布说明<input v-model="publishReason" class="input" maxlength="500" placeholder="说明本次变更与验证结果"></label>
        <p class="hint">版本创建：{{ preview.release.actor }} · {{ preview.release.created_at }}<template v-if="preview.release.published_at">；最近发布：{{ preview.release.published_by || '历史记录' }} · {{ preview.release.published_at }} · {{ preview.release.publish_reason || '未填写说明' }}</template></p>
        <label class="checkbox-row"><input v-model="changedOnly" type="checkbox">仅显示变更文件</label>
        <div class="release-diff"><div class="release-files" aria-label="发布文件清单"><button v-for="file in files" :key="file.path" class="btn" :class="path === file.path ? 'primary' : ''" @click="inspectFile(file.path)">{{ {added:'新增',modified:'修改',deleted:'删除'}[file.kind] || '未修改' }} {{ file.path }}</button></div><div class="release-code"><p class="mono">{{ path || '选择文件查看差异' }}</p><LoadingStatus :active="diffLoading" label="正在读取差异…" /><pre class="log-pre" tabindex="0">{{ diff || '从左侧选择文件。' }}</pre></div></div>
      </section>
      <details v-if="allowOperations && record && !record.deleted_at" class="disclosure"><summary>试运行设置与执行请求</summary><div class="disclosure-body"><TaskOperations :pid="pid" :published="Boolean(record.active_version)" :confirm="confirm" @execution="$emit('execution',$event)" /></div></details>
      <p v-if="!loading && !candidate && !versions.length" class="hint">没有可用代码版本。请配置 GitLab 并完成检查。</p>
    </div>
  </ModalShell>
</template>
<script setup>
import { computed, ref, watch, onBeforeUnmount, defineAsyncComponent } from 'vue';
import { api } from '../api';
import {confirmUnsaved} from '../composables/useUnsavedChanges';
import ModalShell from './ModalShell.vue';
import LoadingStatus from './LoadingStatus.vue';
const TaskOperations=defineAsyncComponent(()=>import('./TaskOperations.vue'));
const props = defineProps({ allowOperations:Boolean, embedded: Boolean, pid: { type: String, default: '' }, confirm: { type: Function, required: true } });
const emit = defineEmits(['close', 'changed', 'execution']);
const record = ref(null), candidate = ref(null), versions = ref([]), preview = ref(null), entry = ref('');
const loading = ref(false), busy = ref(false), busyLabel = ref(''), error = ref(''), message = ref('');
const path = ref(''), diff = ref(''), diffLoading = ref(false);
let generation = 0, timer, alive = true, diffSequence = 0, previewSequence = 0;
const short = value => value?.slice(0, 8) || '—';
const label = value => ({ staged:'待检查', preparing:'检查中', ready:'检查通过', applied:'已发布', failed:'检查失败',cleaned:'已清理' }[value] || value);
const counts = computed(() => Object.fromEntries(['added','modified','deleted'].map(kind => [kind, preview.value?.changes.filter(f => f.kind === kind).length || 0])));
const publishReason=ref('');
const changedOnly = ref(true);
const files = computed(() => { const changes = new Map((preview.value?.changes || []).map(f => [f.path, f.kind])); return [...new Set([...(preview.value?.release.manifest || []).map(f => f.path), ...changes.keys()])].sort().map(path => ({path,kind:changes.get(path)})).filter(file => !changedOnly.value || file.kind); });
const canPublish = computed(() => preview.value && !record.value?.deleted_at && ['ready','applied'].includes(preview.value.release.status) && record.value?.active_version !== preview.value.release.version && preview.value.preflight?.entry_present !== false);
async function close() { if (!busy.value && await confirmUnsaved(props.confirm)) emit('close'); }
function changed() { emit('changed'); window.dispatchEvent(new Event('wfs:task-releases-refresh')); }
async function refresh() {
  const token = generation, pid = props.pid;
  const [state, detail] = await Promise.all([api.gitlabTasks(), api.packages(pid)]);
  if (!alive || token !== generation) return;
  candidate.value = state.items.find(i => i.pid === pid) || null;
  record.value = detail.task || null;
  versions.value = detail.versions || [];
}
async function inspect(version) {
  if (!version) return; const token = generation, request = ++previewSequence; diffSequence++; path.value = ''; diff.value = ''; diffLoading.value = false;
  const data = await api.packagePreview(props.pid, version);
  if (!alive || token !== generation || request !== previewSequence) return;
  preview.value = data; entry.value = data.release.main_file; clearTimeout(timer);
  if (data.release.status === 'preparing') timer = setTimeout(() => work('正在读取依赖检查结果…', async () => { await inspect(version); await refresh(); }), 2000);
}
async function work(text, action) {
  if (busy.value) return; const token = generation; busy.value = true; busyLabel.value = text; error.value = '';
  try { await action(); } catch (err) { if (alive && token === generation) error.value = err.message; }
  finally { if (alive && token === generation) { busy.value = false; busyLabel.value = ''; } }
}
async function inspectFile(filename) {
  const token = generation, request = ++diffSequence; path.value = filename; diffLoading.value = true;
  try { const data = await api.packagePreview(props.pid, preview.value.release.version, filename); if (alive && token === generation && request === diffSequence) diff.value = data.diff || data.content || '文件为空或没有变更。'; }
  catch (err) { if (alive && token === generation && request === diffSequence) error.value = err.message; }
  finally { if (alive && token === generation && request === diffSequence) diffLoading.value = false; }
}
async function stage() { await work('正在获取并校验 GitLab 代码…', async () => { const data = await api.gitlabTaskAction({action:'stage', id:candidate.value.id}); await refresh(); await inspect(data.version); changed(); }); }
async function prepare() { await work('正在准备独立依赖环境…', async () => { await api.packageAction({action:'prepare',pid:props.pid,version:preview.value.release.version,main_file:entry.value}); await inspect(preview.value.release.version); }); }
async function publish() {
  const rollback = Boolean(preview.value.release.published_at);
  if (!await props.confirm({title:rollback ? '回滚任务代码' : '发布任务代码',message:`确认${rollback ? '回滚' : '发布'} ${record.value.task_name}？`,details:['发布后，新的执行使用此版本；已排队或运行的实例继续使用原版本。','保留调度配置、历史版本和业务输出。新任务默认不启用自动调度。'],confirmText:rollback ? '确认回滚' : '确认发布',danger:rollback})) return;
  await work('正在发布并等待调度器确认…', async () => { const version = preview.value.release.version; await api.packageAction({action:rollback ? 'rollback' : 'publish',pid:props.pid,version,revision:record.value.revision,reason:publishReason.value}); await refresh(); await inspect(version); message.value = rollback ? '代码已回滚。' : '任务代码已发布。'; changed(); });
}
async function trial(){if(!await props.confirm({title:'试运行候选版本',message:'此操作会执行候选代码，只提供运行策略中配置的测试连接。',details:['请先确认脚本不会自行连接生产系统或产生外部副作用。','试运行结果单独记录，不替换当前发布版本。'],confirmText:'提交试运行',danger:true}))return;await work('正在提交试运行…',async()=>{await api.submitExecutionRequest(props.pid,{kind:'trial',request_id:crypto.randomUUID().replaceAll('-',''),context:{version:preview.value.release.version}});message.value='试运行请求已保存，可在下方“试运行设置与执行请求”中刷新结果。';});}
async function remove() {
  if (!await props.confirm({title:'确认删除任务',message:`GitLab 已删除 ${candidate.value.task_name}，确认停止后续调度并移入回收站？`,details:['代码历史、日志和输出文件保留，不清理运行中的目录。','已排队或运行的实例继续完成。'],confirmText:'确认删除',danger:true})) return;
  await work('正在删除任务…', async () => { await api.gitlabTaskAction({action:'delete',id:candidate.value.id}); await refresh(); message.value = '任务已移入回收站，输出文件已保留。'; changed(); });
}
async function restore() { await work('正在恢复任务…', async () => { await api.packageAction({action:'restore',pid:props.pid,revision:record.value.revision,reason:publishReason.value}); await refresh(); message.value = '任务已恢复，自动调度保持暂停。'; changed(); }); }
watch(() => props.pid, async pid => {
  const token = ++generation; clearTimeout(timer); diffSequence++; record.value = null; candidate.value = null; versions.value = []; preview.value = null; error.value = ''; message.value = ''; path.value = ''; diff.value = ''; diffLoading.value = false; busy.value = false;
  if (!pid) return; loading.value = true;
  try { await refresh(); if (token === generation && versions.value.length) await inspect(versions.value[0].version); }
  catch (err) { if (alive && token === generation) error.value = err.message; }
  finally { if (alive && token === generation) loading.value = false; }
}, { immediate:true });
onBeforeUnmount(() => { alive = false; generation++; clearTimeout(timer); });
</script>
<style>
.task-release-modal{width:min(1200px,96vw)!important}.release-body{display:grid;gap:20px}.release-body .surface-card{min-width:0}.release-candidate>p,.release-preview>p{margin:14px 0;overflow-wrap:anywhere}.release-candidate.delete{border-color:#a05858}.release-overview,.release-history{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.release-history{max-height:150px;overflow:auto}.release-preview>.form-row{margin:18px 0}.release-diff{display:grid;grid-template-columns:minmax(170px,30%) minmax(0,1fr);gap:20px;margin-top:24px}.release-files{display:grid;gap:8px;align-content:start;max-height:500px;overflow:auto}.release-files .btn{text-align:left;overflow-wrap:anywhere;white-space:normal}.release-code{min-width:0}.release-code>p{margin-bottom:12px;overflow-wrap:anywhere}.release-code pre{min-height:220px;max-height:480px;white-space:pre;overflow:auto;font-size:12px}@media(max-width:720px){.release-diff{grid-template-columns:1fr}.release-files{max-height:200px}}
</style>
