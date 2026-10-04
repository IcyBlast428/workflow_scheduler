<template>
  <section class="panel package-panel">
    <div class="panel-head"><div><h2>任务发布</h2><p>上传完整任务包，检查差异后发布。每个版本独立保存，代码保持只读。</p></div><div class="filter-actions"><button class="btn" :disabled="loading || busy" @click="refresh">{{ loading ? '刷新中…' : '刷新' }}</button><button class="btn primary" :disabled="busy" @click="newTask">新增任务</button></div></div>
    <LoadingStatus :active="loading || busy" :label="busyLabel || '正在更新任务与版本…'" />
    <div class="panel-body">
      <div v-if="error" class="inline-alert danger" role="alert">{{ error }}</div><div v-if="message" class="inline-alert success" role="status">{{ message }}</div>
      <div class="package-layout">
        <aside class="package-sidebar">
          <div class="form-row"><label for="package-search">查找任务</label><input id="package-search" v-model="search" class="input" placeholder="名称、分类或编号"></div>
          <div class="filter-actions"><button class="btn" :class="!trash ? 'primary' : ''" :aria-pressed="!trash" @click="trash = false">任务 {{ tasks.filter(t => !t.deleted_at).length }}</button><button class="btn" :class="trash ? 'primary' : ''" :aria-pressed="trash" @click="trash = true">回收站 {{ tasks.filter(t => t.deleted_at).length }}</button></div>
          <div class="package-task-list" aria-label="任务发布列表"><button v-for="item in filtered" :key="item.pid" class="package-task" :class="selected?.pid === item.pid ? 'selected' : ''" :disabled="busy" @click="select(item)"><strong>{{ item.task_name }}</strong><span>{{ item.group_name }} / {{ item.folder_name }}</span><small>{{ item.deleted_at ? '已删除' : item.unmanaged ? 'Git 任务 · 可导入' : item.active_version ? `当前 ${short(item.active_version)}` : item.legacy ? '仍使用原 Git 代码' : '待首次发布' }}</small></button><p v-if="!filtered.length" class="hint package-empty">{{ trash ? '回收站为空' : '没有符合条件的任务' }}</p></div>
        </aside>
        <div class="package-workspace">
          <section v-if="creating" class="surface-card">
            <div class="section-heading"><h3>新增任务</h3><p>首次发布后进入任务列表，默认不启用自动调度。</p></div>
            <form class="package-form" @submit.prevent="upload">
              <div class="form-row"><label for="package-name">任务名称</label><input id="package-name" v-model.trim="form.task_name" class="input" maxlength="200" required placeholder="如：日报汇总"></div>
              <div class="form-row"><label for="package-group">任务分类</label><input id="package-group" v-model.trim="form.group_name" class="input" list="package-groups" maxlength="80" required placeholder="如：报表"><datalist id="package-groups"><option v-for="group in groups" :key="group" :value="group" /></datalist></div>
              <div class="form-row"><label for="package-folder">目录名称</label><input id="package-folder" v-model.trim="form.folder_name" class="input" maxlength="80" required placeholder="如：daily_report"><small class="hint">文字、数字、下划线或连字符；同分类内唯一。</small></div>
              <div class="form-row"><label for="new-package-note">版本说明</label><input id="new-package-note" v-model="form.note" class="input" maxlength="1000" placeholder="简要记录本次变更"></div>
              <div class="package-upload full"><label for="new-package-file">完整任务包（ZIP）</label><input id="new-package-file" type="file" accept=".zip,application/zip" required @change="chooseFile"><p class="hint">支持多个代码、SQL、说明和资源文件，上限 {{ maxMB }} MiB。请移除 .git、.venv、.env、身份文件和缓存目录。</p></div>
              <div class="filter-actions full"><button class="btn primary" :disabled="busy || !file">上传并检查文件</button><button class="btn" type="button" :disabled="busy" @click="creating = false">取消</button></div>
            </form>
          </section>
          <template v-else-if="selected">
            <section class="surface-card package-overview">
              <div class="section-heading"><h3>{{ selected.task_name }}</h3><p>{{ selected.group_name }} / {{ selected.folder_name }}</p><p class="mono">{{ selected.pid }}</p></div>
              <div class="filter-actions"><span class="tag" :class="selected.deleted_at ? 'warning' : 'info'">{{ selected.deleted_at ? '回收站' : selected.active_version ? `当前版本 ${short(selected.active_version)}` : selected.unmanaged || selected.legacy ? '使用原 Git 代码' : '未发布' }}</span><button v-if="selected.unmanaged" class="btn primary" :disabled="busy" @click="importExisting">导入版本管理</button><button v-else-if="selected.deleted_at" class="btn primary" :disabled="busy" @click="restore">恢复任务（暂停）</button><button v-else class="btn danger" :disabled="busy" @click="remove">移入回收站</button><button v-if="!selected.deleted_at && (selected.active_version || selected.legacy || selected.unmanaged)" class="btn" @click="$emit('detail',selected.pid)">任务详情与调度配置</button></div>
              <p v-if="selected.unmanaged" class="hint">导入复制完整代码并保留编号、配置和日志。检查并发布初始版本之前，任务继续使用原 Git 代码。</p><p v-else-if="selected.deleted_at" class="hint">代码、配置和日志都已保留；删除前已排队或运行的实例继续完成。恢复后保持暂停。</p><p v-else class="hint">代码发布与回滚保留当前调度配置；调度配置可在任务详情的配置历史中单独恢复。</p>
            </section>
            <section v-if="!selected.unmanaged && !selected.deleted_at" class="surface-card"><details class="package-upload-disclosure" :open="!versions.length"><summary>上传新版本</summary><form class="package-form" @submit.prevent="upload"><div class="package-upload full"><label for="update-package-file">完整任务包（ZIP）</label><input id="update-package-file" type="file" accept=".zip,application/zip" required @change="chooseFile"><p class="hint">完整替换代码文件；缺少的文件会列入删除清单。上限 {{ maxMB }} MiB。</p></div><div class="form-row full"><label for="update-package-note">版本说明</label><input id="update-package-note" v-model="form.note" class="input" maxlength="1000" placeholder="本次修复或新增内容"></div><button class="btn primary" :disabled="busy || !file">上传并预览差异</button></form></details></section>
            <section v-if="versions.length" class="surface-card"><div class="section-heading"><h3>版本历史</h3><p>显示最近 50 个版本；已有代码和历史执行不会被覆盖。</p></div><div class="package-version-list" aria-label="版本历史"><button v-for="item in versions" :key="item.version" class="package-version" :class="preview?.release.version === item.version ? 'selected' : ''" :disabled="busy" @click="inspect(item.version)"><div><strong class="mono">{{ short(item.version) }}</strong><span class="tag" :class="stateClass(item.status)">{{ selected.active_version === item.version ? '当前使用' : stateLabel(item.status) }}</span></div><p>{{ item.note || '未填写说明' }}</p><small>{{ item.created_at.split('.')[0] }} · {{ item.actor }} · {{ item.file_count }} 个文件</small></button></div></section>
            <section v-if="preview" class="surface-card package-preview" aria-label="版本预览">
              <div class="section-heading"><h3>版本 {{ short(preview.release.version) }}</h3><p>{{ preview.against_version ? `与当前版本 ${short(preview.against_version)} 比较` : '初始版本文件清单' }}</p></div>
              <div class="package-steps" aria-label="发布步骤"><span class="tag success">1 文件已检查</span><span class="tag" :class="stateClass(preview.release.status)">2 {{ preview.release.status === 'applied' ? '环境检查通过' : stateLabel(preview.release.status) }}</span><span class="tag" :class="selected.active_version === preview.release.version ? 'success' : 'info'">3 {{ selected.active_version === preview.release.version ? '调度器已确认' : '等待发布' }}</span></div>
              <p v-if="preview.release.message" class="inline-alert" :class="preview.release.status === 'failed' ? 'danger' : 'info'">{{ preview.release.message }}</p>
              <div class="form-row"><label for="package-entry">Python 入口</label><select id="package-entry" v-model="entry" class="select" :disabled="busy || !['staged','failed'].includes(preview.release.status)"><option value="" disabled>请选择入口</option><option v-for="item in preview.release.manifest.filter(f => f.path.endsWith('.py'))" :key="item.path" :value="item.path">{{ item.path }}</option></select></div>
              <div class="package-dependencies"><strong>独立依赖环境</strong><p class="hint">{{ preview.release.requirements.length ? preview.release.requirements.join('，') : '未声明第三方依赖，使用独立的 Python 标准库环境。' }}</p><p class="hint">所有第三方依赖及其间接依赖逐行写入 requirements.txt（package==version），并提供 wheels/ 或服务端离线依赖库。不继承原任务或平台环境，检查时不会执行业务代码。</p><p class="hint">代码目录只读；业务输出请写入 WFS_TASK_DATA_DIR 指定的目录，更新与回滚都会保留。</p></div>
              <p class="hint mono package-checksum">包校验 SHA256：{{ preview.release.checksum }}</p>
              <div class="filter-actions"><button v-if="['staged','failed'].includes(preview.release.status) && !selected.deleted_at" class="btn primary" :disabled="busy || !entry" @click="prepare">检查依赖环境</button><button v-if="canPublish" class="btn primary" :disabled="busy" @click="activate">{{ preview.release.published_at ? '回滚到此版本' : '发布此版本' }}</button><span v-if="preview.release.status === 'preparing'" class="tag warning" role="status">{{ preview.release.prepare_stage || '准备依赖中' }} · 已用 {{ preparationSeconds }} 秒</span><a class="btn" :href="downloadUrl" download>下载此任务包</a></div>
              <div class="package-diff-layout"><div class="package-files" aria-label="文件清单"><div class="section-heading"><h4>文件与变更</h4><p>新增 {{ counts.added }} · 修改 {{ counts.modified }} · 删除 {{ counts.deleted }}</p></div><button v-for="item in fileList" :key="item.path" class="package-file" :class="path === item.path ? 'selected' : ''" :disabled="diffLoading" @click="inspectFile(item.path)"><span class="tag" :class="{added:'success',modified:'warning',deleted:'danger'}[item.kind] || 'info'">{{ {added:'新增',modified:'修改',deleted:'删除'}[item.kind] || '相同' }}</span><span>{{ item.path }}</span></button></div><div class="package-diff"><div class="section-heading"><h4>{{ path || '选择文件查看' }}</h4><p>代码只读；+ 表示新增行，− 表示删除行。</p></div><LoadingStatus :active="diffLoading" label="正在读取文件差异…" /><pre class="log-pre" tabindex="0">{{ diff || '从左侧选择文件，查看文本内容或版本差异。' }}</pre></div></div>
            </section>
          </template>
          <section v-else class="surface-card package-welcome"><div class="section-heading"><h3>让任务变更更清楚</h3><p>从左侧选择现有任务，或上传一个新任务。</p></div><ol><li>上传完整 ZIP，查看每个文件的变更。</li><li>选择入口，检查语法与离线依赖。</li><li>确认发布后，后续执行使用新版本。</li></ol><button class="btn primary" @click="newTask">新增任务</button></section>
        </div>
      </div>
    </div>
  </section>
</template>
<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue';
import { timestamp } from '../timebase';
import { api } from '../api';
import LoadingStatus from './LoadingStatus.vue';
const props = defineProps({ confirm: {type:Function,required:true}, initialPid: {type:String,default:''} });
const emit = defineEmits(['changed','detail']);
const tasks = ref([]), versions = ref([]), selected = ref(null), preview = ref(null);
const loading = ref(false), busy = ref(false), busyLabel = ref(''), error = ref(''), message = ref('');
const creating = ref(false), trash = ref(false), search = ref(''), file = ref(null), entry = ref('');
const path = ref(''), diff = ref(''), diffLoading = ref(false), maxMB = ref(64);
const form = reactive({task_name:'',group_name:'',folder_name:'',note:''});
const preparationSeconds = computed(() => preview.value?.release.prepare_started_at ? Math.max(0,Math.floor((Date.now()-timestamp(preview.value.release.prepare_started_at))/1000)) : 0);
let timer, generation = 0, stopped = false;
const short = value => value?.slice(0,8) || '—';
const stateLabel = status => ({staged:'等待依赖检查',preparing:'准备依赖中',ready:'检查通过',applied:'曾发布',failed:'检查失败'})[status] || status;
const stateClass = status => ({staged:'info',preparing:'warning',ready:'success',applied:'success',failed:'danger'})[status] || 'info';
const filtered = computed(() => tasks.value.filter(t => Boolean(t.deleted_at) === trash.value && [t.task_name,t.pid,t.group_name].join(' ').toLowerCase().includes(search.value.toLowerCase())));
const groups = computed(() => [...new Set(tasks.value.map(t => t.group_name))]);
const counts = computed(() => Object.fromEntries(['added','modified','deleted'].map(kind => [kind,preview.value?.changes.filter(f => f.kind === kind).length || 0])));
const fileList = computed(() => { if (!preview.value) return []; const changes = new Map(preview.value.changes.map(f => [f.path,f.kind])); return [...new Set([...preview.value.release.manifest.map(f => f.path),...changes.keys()])].sort().map(path => ({path,kind:changes.get(path)})); });
const canPublish = computed(() => preview.value && !selected.value?.deleted_at && ['ready','applied'].includes(preview.value.release.status) && selected.value?.active_version !== preview.value.release.version);
const downloadUrl = computed(() => '/api/taskinfo/packages/download?' + new URLSearchParams({pid:selected.value?.pid || '',version:preview.value?.release.version || ''}));
function resetPreview() { generation++; clearTimeout(timer); preview.value = null; path.value = ''; diff.value = ''; diffLoading.value = false; loading.value = false; }
function newTask() { if (busy.value) return; resetPreview(); selected.value = null; versions.value = []; creating.value = true; error.value = ''; message.value = ''; file.value = null; Object.assign(form,{task_name:'',group_name:'',folder_name:'',note:''}); }
function chooseFile(event) { file.value = event.target.files[0] || null; if (file.value && file.value.size > maxMB.value * 1024**2) { error.value = `任务包不能超过 ${maxMB.value} MiB。`; file.value = null; } }
async function work(label, action) { if (busy.value) return; busy.value = true; busyLabel.value = label; error.value = ''; message.value = ''; try { await action(); } catch (err) { error.value = err.message; } finally { busy.value = false; busyLabel.value = ''; } }
async function refresh() {
  if (loading.value || stopped) return; loading.value = true; const token = generation;
  try { const data = await api.packages(); if (stopped || token !== generation) return; tasks.value = data.tasks; maxMB.value = data.limits.upload_bytes / 1024**2;
    const pid = selected.value?.pid || props.initialPid;
    if (pid && !creating.value && token === generation) { const item = tasks.value.find(t => t.pid === pid); if (item) { selected.value = item; if (!item.unmanaged) { const detail = await api.packages(pid); if (token === generation) { selected.value = detail.task; versions.value = detail.versions;
      const version = preview.value?.release.version || detail.versions[0]?.version;
      if (version) { const data = await api.packagePreview(pid,version); if (token === generation && !stopped) { if (preview.value?.against_version !== data.against_version) { path.value = ''; diff.value = ''; } preview.value = data; entry.value = data.release.main_file; if (data.release.status === 'preparing') poll(token); } }
    } } } }
  } catch (err) { if (token === generation && !stopped) error.value = err.message; } finally { if (token === generation && !stopped) loading.value = false; }
}
async function select(item) {
  resetPreview(); const token = generation; selected.value = item; creating.value = false; versions.value = []; error.value = ''; message.value = ''; file.value = null; form.note = '';
  if (item.unmanaged) return; loading.value = true;
  try { const detail = await api.packages(item.pid); if (token !== generation || stopped) return; selected.value = detail.task; versions.value = detail.versions; await inspect(detail.versions[0]?.version); } catch (err) { if (token === generation && !stopped) error.value = err.message; } finally { if (token === generation && !stopped) loading.value = false; }
}
async function inspect(version) {
  if (!version || !selected.value) return; const pid = selected.value.pid, token = ++generation; clearTimeout(timer); path.value = ''; diff.value = ''; loading.value = true;
  try { const data = await api.packagePreview(pid,version); if (token !== generation || stopped) return; preview.value = data; entry.value = data.release.main_file; if (data.release.status === 'preparing') poll(token); } catch (err) { if (token === generation && !stopped) error.value = err.message; } finally { if (token === generation && !stopped) loading.value = false; }
}
async function inspectFile(filename) {
  const token = generation, pid = selected.value.pid, version = preview.value.release.version; diffLoading.value = true; path.value = filename;
  try { const data = await api.packagePreview(pid,version,filename); if (token === generation && !stopped && path.value === filename) diff.value = data.diff || data.content || '文件为空或未发生变更。'; } catch (err) { if (token === generation && !stopped && path.value === filename) error.value = err.message; } finally { if (token === generation && !stopped) diffLoading.value = false; }
}
function poll(token) {
  clearTimeout(timer); timer = window.setTimeout(async () => {
    if (token !== generation || stopped || !preview.value) return;
    try { const data = await api.packagePreview(selected.value.pid,preview.value.release.version); if (token !== generation || stopped) return; preview.value = data; if (data.release.status === 'preparing') poll(token); else { await refresh(); if (token === generation && !stopped && data.release.status === 'failed') error.value = data.release.message; } } catch (err) { if (token === generation && !stopped) { error.value = err.message; poll(token); } }
  },2000);
}
async function upload() {
  if (!file.value) return;
  await work('正在上传并检查任务文件…',async () => { const body = new FormData(); body.append('package',file.value); body.append('note',form.note); if (creating.value) for (const key of ['task_name','group_name','folder_name']) body.append(key,form[key]); else body.append('pid',selected.value.pid);
    const data = await api.uploadPackage(body); creating.value = false; file.value = null; selected.value = {pid:data.pid}; await refresh(); await inspect(data.version); message.value = '任务包已保存，请选择入口并检查依赖环境。'; });
}
async function importExisting() { await work('正在复制现有任务代码…',async () => { const data = await api.packageAction({action:'import',pid:selected.value.pid}); await refresh(); await inspect(data.version); message.value = '初始版本已导入。原任务继续运行，检查依赖后可发布。'; }); }
async function prepare() { await work('正在提交依赖检查…',async () => { await api.packageAction({action:'prepare',pid:selected.value.pid,version:preview.value.release.version,main_file:entry.value}); await inspect(preview.value.release.version); }); }
async function activate() {
  const version = preview.value.release.version, rollback = Boolean(preview.value.release.published_at);
  if (!await props.confirm({title:rollback ? '回滚任务代码' : '发布任务版本',message:`${selected.value.task_name} 将从 ${short(selected.value.active_version)} 切换为 ${short(version)}。`,details:[`新增 ${counts.value.added}、修改 ${counts.value.modified}、删除 ${counts.value.deleted} 个文件。`,'保留当前调度配置；已经排队或运行的实例继续使用原版本。'],confirmText:rollback ? '确认回滚' : '确认发布',danger:rollback})) return;
  await work('正在发布并等待调度器确认…',async () => { await api.packageAction({action:rollback ? 'rollback' : 'publish',pid:selected.value.pid,version,revision:selected.value.revision}); await refresh(); await inspect(version); message.value = rollback ? '代码已回滚，调度配置保持原样。' : '版本已生效；新任务可在任务列表配置自动调度。'; emit('changed'); });
}
async function remove() {
  if (!await props.confirm({title:'移入回收站',message:`停止 ${selected.value.task_name} 的后续调度和新手动执行。`,details:['保留所有代码版本、配置与历史日志。','已经排队或运行的实例继续完成；恢复后保持暂停。'],confirmText:'移入回收站',danger:true})) return;
  await work('正在停止后续调度并移入回收站…',async () => { await api.packageAction({action:'trash',pid:selected.value.pid,revision:selected.value.revision}); trash.value = true; await refresh(); message.value = '任务已移入回收站。'; emit('changed'); });
}
async function restore() { await work('正在恢复任务…',async () => { await api.packageAction({action:'restore',pid:selected.value.pid,revision:selected.value.revision}); trash.value = false; await refresh(); message.value = '任务已恢复，自动调度保持暂停。'; emit('changed'); }); }
onMounted(() => { refresh(); window.addEventListener('wfs:packages-refresh',refresh); });
onBeforeUnmount(() => { stopped = true; generation++; clearTimeout(timer); window.removeEventListener('wfs:packages-refresh',refresh); });
</script>
<style scoped>
.package-layout{display:grid;grid-template-columns:260px minmax(0,1fr);gap:24px;align-items:start}.package-sidebar,.package-workspace{min-width:0}.package-sidebar{display:grid;gap:16px}.package-task-list{display:grid;gap:8px;max-height:75vh;overflow:auto;padding:2px}.package-task,.package-version,.package-file{font:inherit;color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);text-align:left;padding:14px;cursor:pointer;min-width:0}.package-task{display:grid;gap:6px;width:100%}.package-task span,.package-task small,.package-version small{color:var(--muted);font-size:12px;overflow-wrap:anywhere}.selected{border-color:var(--brand)!important;background:var(--brand-soft)!important}.package-workspace{display:grid;gap:20px}.package-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.full{grid-column:1/-1}.package-upload{display:grid;gap:12px;padding:18px;border:1px dashed var(--line);border-radius:var(--radius)}.package-upload input{font:inherit;max-width:100%;color:var(--muted)}.package-upload input::file-selector-button{font:inherit;padding:9px 14px;border:1px solid var(--line);border-radius:var(--radius);background:var(--button-bg);color:var(--ink);margin-right:12px;cursor:pointer}.package-upload-disclosure>summary{cursor:pointer;font-weight:600;padding:4px 0}.package-upload-disclosure .package-form{margin-top:18px}.package-version-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;max-height:360px;overflow:auto;padding:2px}.package-version>div{display:flex;gap:12px;align-items:center;justify-content:space-between}.package-version p{margin:12px 0;overflow-wrap:anywhere}.package-steps{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px}.package-preview>.form-row,.package-dependencies,.package-preview>.filter-actions{margin:18px 0}.package-dependencies{padding:16px;border:1px solid var(--line);border-radius:var(--radius)}.package-diff-layout{display:grid;grid-template-columns:minmax(160px,30%) minmax(0,1fr);gap:20px;margin-top:24px;border-top:1px solid var(--line);padding-top:22px}.package-files{display:grid;align-content:start;gap:8px;max-height:560px;overflow:auto;padding:2px}.package-file{display:flex;align-items:center;gap:10px;padding:10px;overflow-wrap:anywhere;width:100%}.package-file span:last-child{min-width:0;word-break:break-word}.package-diff{min-width:0}.package-diff .log-pre{min-height:240px;max-height:480px;white-space:pre;overflow:auto;font-size:12px}.package-checksum,.package-overview .mono{overflow-wrap:anywhere;word-break:break-word}.package-empty{padding:14px}.package-welcome ol{padding-left:24px;line-height:2.2;margin:18px 0}.package-panel .section-heading p{margin-top:8px}.package-panel button:disabled{cursor:default}
@media(max-width:1000px){.package-layout{grid-template-columns:210px minmax(0,1fr)}.package-diff-layout{grid-template-columns:1fr}.package-files{max-height:220px}}
@media(max-width:720px){.package-layout,.package-form{grid-template-columns:1fr}.package-task-list{max-height:230px}.package-version-list{grid-template-columns:1fr}.package-sidebar{border-bottom:1px solid var(--line);padding-bottom:20px}.package-upload{padding:14px}}
</style>
