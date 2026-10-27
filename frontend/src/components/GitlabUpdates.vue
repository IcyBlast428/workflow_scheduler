<template>
  <div class="gitlab-workspace">
    <section class="surface-card gitlab-intro">
      <div class="gitlab-heading">
        <div><h2>GitLab 代码更新</h2><p class="hint">查看待合并分支，以及与已部署提交的差异。合并操作在 GitLab 完成，任务和平台分别发布。</p></div>
        <div class="gitlab-actions">
          <button class="btn" :disabled="loading" @click="refresh">刷新列表</button>
          <button class="btn primary" :disabled="!settings?.enabled || state?.scanning || checking" @click="scan">{{ state?.scanning || checking ? '正在检查…' : '立即检查' }}</button>
        </div>
      </div>
      <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p>
      <p v-if="message" class="inline-alert success" role="status">{{ message }}</p>
      <div v-if="state" class="gitlab-status">
        <span class="badge">待合并 {{ state.pending_merge }}</span><span class="badge">待部署 / 发布 {{ state.pending_release }}</span>
        <span class="hint">最近检查：{{ timeLabel(state.checked_at) }}</span>
        <button v-if="state.unread" class="btn" @click="acknowledge">标记本批已读</button>
      </div>
      <p v-if="state?.error" class="inline-alert danger" role="alert">{{ state.error }}<span v-if="state.count"> 当前保留上次结果，请检查恢复后再核对。</span></p>
      <ul v-if="state?.warnings?.length" class="gitlab-warnings"><li v-for="warning in state.warnings" :key="warning">{{ warning }}</li></ul>
    </section>

    <details v-if="settings" class="surface-card gitlab-settings" :open="!settings.url">
      <summary>GitLab 连接与目录规则 <span class="hint">{{ settings.enabled ? '已启用自动检查' : '尚未启用' }}</span></summary>
      <form @submit.prevent="save">
        <fieldset :disabled="saving">
          <div class="gitlab-form-grid">
            <label>GitLab 地址<input v-model.trim="form.url" class="input" type="url" required placeholder="https://gitlab.example.internal" maxlength="1000"></label>
            <label>项目 ID 或路径<input v-model.trim="form.project" class="input" required placeholder="group/project" maxlength="300"></label>
            <label>目标分支<input v-model.trim="form.target" class="input" required maxlength="200"></label>
            <label>检查间隔（秒）<input v-model.number="form.interval" class="input" type="number" min="60" max="3600" required></label>
            <label>只读访问令牌<input v-model="form.token" class="input" type="password" autocomplete="new-password" maxlength="2048" :placeholder="settings.token_set ? '已保存，留空保留' : '私有项目需要 read_api 权限'"></label>
            <label>HTTPS 内部 CA 路径（可选）<input v-model.trim="form.ca_bundle" class="input" maxlength="1024" placeholder="服务端可读的 CA 文件路径"></label>
            <label>任务代码根目录（每行一项）<textarea v-model="taskRoots" class="input" rows="3" required></textarea></label>
            <label>公共模块 / 依赖路径（每行一项）<textarea v-model="sharedPaths" class="input" rows="3" required></textarea></label>
          </div>
          <div class="gitlab-actions gitlab-options">
            <label><input v-model="form.enabled" type="checkbox"> 自动检查</label>
            <label><input v-model="form.allow_http" type="checkbox"> 允许内网 HTTP（令牌将通过明文连接传输）</label>
            <label v-if="settings.token_set"><input v-model="form.clear_token" type="checkbox"> 清除已保存令牌</label>
          </div>
          <div class="gitlab-baseline">
            <label for="gitlab-platform-commit">平台当前已部署提交（完整 SHA，可稍后填写）</label>
            <div class="gitlab-actions"><input id="gitlab-platform-commit" v-model.trim="form.platform_commit" class="input" maxlength="64" placeholder="留空时仅检查待合并分支"><button v-if="settings.running_commit" class="btn" type="button" @click="form.platform_commit = settings.running_commit">使用当前程序提交</button></div>
            <small class="hint">请确认提交属于此 GitLab 项目。“已读”不会改变部署基线；平台升级后再核对更新。</small>
          </div>
          <div class="gitlab-binding-head"><strong>任务目录与已发布提交</strong><button class="btn" type="button" @click="form.tasks.push({ pid: '', path: '', commit: '' })">添加任务绑定</button></div>
          <p class="hint">旧 ZIP 版本没有 Git 来源记录，请首次确认对应提交。绑定后可以发现目标分支中已合并、尚未发布的任务变更。</p>
          <div v-for="(task, index) in form.tasks" :key="index" class="gitlab-binding">
            <label>任务编号<select v-model="task.pid" class="select" required><option value="">选择任务</option><option v-for="item in tasks" :key="item.pid" :value="item.pid">{{ item.task_name }} · {{ item.pid }}</option><option v-if="task.pid && !tasks.some(item => item.pid === task.pid)" :value="task.pid">{{ task.pid }}</option></select></label>
            <label>仓库中的任务目录<input v-model.trim="task.path" class="input" required placeholder="app/jobs/group/job"></label>
            <label>当前已发布提交<input v-model.trim="task.commit" class="input" maxlength="64" placeholder="完整提交 SHA"></label>
            <button class="btn" type="button" :aria-label="`移除任务绑定 ${index + 1}`" @click="form.tasks.splice(index, 1)">移除</button>
          </div>
          <p class="hint">任务目录优先匹配，公共路径显示为公共变更，其余文件归为平台变更。移动或删除文件会同时检查原路径。</p>
          <button class="btn primary" type="submit">{{ saving ? '保存中…' : '保存 GitLab 设置' }}</button>
        </fieldset>
      </form>
    </details>

    <p v-if="loading && !state" role="status">正在读取更新列表…</p>
    <section v-if="state && !state.count" class="surface-card gitlab-empty">
      <h3>{{ !state.enabled ? '连接 GitLab，集中查看代码更新' : state.scanning ? '正在获取分支与差异' : state.error || state.warnings?.length ? '当前没有可展示的更新，请先核对上方检查状态' : !state.checked_at ? '等待首次检查' : '本次检查没有发现代码差异' }}</h3>
      <p class="hint">配置保存在本机服务的数据目录。第一版不会自动合并、拉取覆盖运行代码或触发发布。</p>
    </section>
    <div v-if="state?.count" class="gitlab-review-layout">
      <section class="surface-card gitlab-update-list" aria-label="代码更新列表">
        <div class="gitlab-filters"><button v-for="choice in filters" :key="choice.id" class="btn" :aria-pressed="filter === choice.id" @click="filter = choice.id">{{ choice.label }}</button></div>
        <button v-for="item in filtered" :key="item.id" class="gitlab-update-row" :class="{ selected: selected?.id === item.id }" @click="select(item)">
          <span class="gitlab-row-title">{{ kindLabel(item.kind) }} · {{ item.kind === 'task' ? item.pid : item.branch }}</span>
          <span class="hint">{{ short(item.base) }} → {{ short(item.head) }} · {{ item.files.length }} 个文件</span>
          <span class="gitlab-badges"><span v-for="category in item.categories" :key="category" class="badge">{{ categoryLabel(category) }}</span><span v-if="item.incomplete" class="badge">差异不完整</span></span>
        </button>
        <p v-if="!filtered.length" class="hint">此筛选下没有更新。</p>
      </section>
      <section v-if="selected" class="surface-card gitlab-review" aria-label="代码差异审查">
        <div class="gitlab-heading"><div><h3>{{ kindLabel(selected.kind) }}：{{ selected.kind === 'task' ? selected.pid : selected.branch }}</h3><p class="hint">{{ selected.kind === 'branch' ? `相对目标分支 ${selected.target} 的待合并差异` : '目标分支与确认的已部署版本之间的差异' }}</p></div><div class="gitlab-actions"><a class="btn" :href="selected.compare_url" target="_blank" rel="noopener noreferrer">在 GitLab 查看完整差异</a><a v-if="selected.merge_url" class="btn primary" :href="selected.merge_url" target="_blank" rel="noopener noreferrer">去 GitLab 查看合并请求</a></div></div>
        <div class="gitlab-shas"><span>基线 <code>{{ selected.base }}</code></span><span>候选 <code>{{ selected.head }}</code></span></div>
        <p v-if="selected.tasks.length" class="hint">涉及任务：{{ selected.tasks.join('、') }}</p>
        <p v-if="selected.incomplete" class="inline-alert warning">此次差异可能不完整，请在 GitLab 核对后再处理。</p>
        <details v-if="selected.commits.length"><summary>比对范围内的提交（{{ selected.commits.length }}）</summary><ul class="gitlab-commits"><li v-for="commit in selected.commits" :key="commit.sha"><code>{{ short(commit.sha) }}</code> {{ commit.title }} <span class="hint">{{ commit.author }}</span></li></ul></details>
        <div class="gitlab-file-layout">
          <div class="gitlab-files" aria-label="修改文件"><button v-for="(file, index) in selected.files" :key="index" class="btn" :aria-pressed="fileIndex === index" @click="loadDiff(index)"><span>{{ fileKind(file.kind) }}</span><span>{{ file.path }}</span><small v-if="file.kind === 'renamed'">原路径：{{ file.old_path }}</small></button></div>
          <div class="gitlab-diff"><p v-if="diffLoading" role="status">正在读取差异…</p><p v-else-if="diffError" class="inline-alert danger" role="alert">{{ diffError }}<button class="btn" @click="loadDiff(fileIndex)">重试</button></p><template v-else-if="fileDiff"><p v-if="fileDiff.truncated" class="inline-alert warning">文件内容已截断或 GitLab 未提供完整差异。</p><pre tabindex="0" aria-label="文件差异"><code><span v-for="(line, index) in diffLines" :key="index" :class="line.startsWith('+') ? 'diff-add' : line.startsWith('-') ? 'diff-delete' : ''">{{ line }}{{ '\n' }}</span></code></pre><p v-if="!fileDiff.diff" class="hint">此文件没有可展示的文本差异，可能是二进制文件、路径或文件属性变化。</p></template><p v-else class="hint">选择文件查看差异。</p></div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue';
import { api } from '../api';
const emit = defineEmits(['state']);
const settings = ref(null), state = ref(null), tasks = ref([]), loading = ref(false), saving = ref(false), checking = ref(false);
const error = ref(''), message = ref(''), selected = ref(null), fileDiff = ref(null), fileIndex = ref(-1), diffLoading = ref(false), diffError = ref('');
const form = reactive({ tasks: [] }), taskRoots = ref(''), sharedPaths = ref(''), filter = ref('all');
let timer, sequence = 0, stateSequence = 0, alive = true;
const filters = [{ id: 'all', label: '全部' }, { id: 'branch', label: '待合并' }, { id: 'release', label: '待部署 / 发布' }];
const filtered = computed(() => (state.value?.items || []).filter(item => filter.value === 'all' || (filter.value === 'branch' ? item.kind === 'branch' : item.kind !== 'branch')));
const diffLines = computed(() => (fileDiff.value?.diff || '').split('\n'));
const short = value => value?.slice(0, 8) || '—';
const timeLabel = value => value ? new Date(value * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚未检查';
const kindLabel = kind => ({ branch: '待合并', platform: '平台待部署', task: '任务待发布' }[kind] || kind);
const categoryLabel = value => ({ platform: '平台代码', task: '任务代码', shared: '公共变更' }[value] || value);
const fileKind = value => ({ added: '新增', modified: '修改', deleted: '删除', renamed: '移动' }[value] || value);
function applySettings(value) {
  settings.value = value;
  Object.assign(form, JSON.parse(JSON.stringify(value)), { token: '', clear_token: false });
  taskRoots.value = value.task_roots.join('\n'); sharedPaths.value = value.shared_paths.join('\n');
}
function applyState(value) {
  state.value = value; emit('state', value);
  if (selected.value && !value.items.some(item => item.id === selected.value.id)) {
    sequence += 1; selected.value = null; fileDiff.value = null; fileIndex.value = -1;
  }
  if (selected.value) {
    const latest = value.items.find(item => item.id === selected.value.id);
    if (latest && latest.files[fileIndex.value]?.path !== selected.value.files[fileIndex.value]?.path) select(latest);
    else if (latest) selected.value = latest;
  }
  if (!selected.value && value.items.length) select(value.items[0]);
}
async function refresh() {
  const current = ++stateSequence;
  loading.value = true; error.value = '';
  try { const value = await api.gitlabState(); if (alive && current === stateSequence) applyState(value); }
  catch (exc) { if (alive && current === stateSequence) error.value = exc.message; }
  finally { if (alive && current === stateSequence) loading.value = false; }
}
async function save() {
  stateSequence += 1;
  saving.value = true; error.value = ''; message.value = '';
  try {
    const value = await api.saveGitlabConfiguration({ ...form, task_roots: taskRoots.value.split('\n').map(v => v.trim()).filter(Boolean), shared_paths: sharedPaths.value.split('\n').map(v => v.trim()).filter(Boolean) });
    if (!alive) return;
    applySettings(value); message.value = '设置已保存。自动检查由调度服务执行；也可以立即检查。'; await refresh();
  } catch (exc) { if (alive) error.value = exc.message; }
  finally { if (alive) saving.value = false; }
}
async function scan() {
  const current = ++stateSequence;
  checking.value = true; error.value = '';
  try { const value = await api.scanGitlab(); if (alive && current === stateSequence) applyState(value); }
  catch (exc) { if (alive) error.value = exc.message; }
  finally { if (alive) checking.value = false; }
}
async function acknowledge() {
  try { await api.acknowledgeGitlab(state.value.fingerprint); if (alive) await refresh(); }
  catch (exc) { if (alive) error.value = exc.message; }
}
function select(item) { selected.value = item; fileDiff.value = null; fileIndex.value = -1; sequence += 1; if (item.files.length) loadDiff(0); }
async function loadDiff(index) {
  if (!selected.value) return;
  const current = ++sequence, id = selected.value.id;
  fileIndex.value = index; fileDiff.value = null; diffLoading.value = true; diffError.value = '';
  try { const value = await api.gitlabDiff(id, index); if (alive && current === sequence && selected.value?.id === id) fileDiff.value = value; }
  catch (exc) { if (alive && current === sequence) diffError.value = exc.message; }
  finally { if (alive && current === sequence) diffLoading.value = false; }
}
onMounted(async () => {
  try {
    const [configuration, packages] = await Promise.all([api.gitlabConfiguration(), api.packages()]);
    if (!alive) return;
    applySettings(configuration); tasks.value = packages.tasks.filter(task => !task.deleted_at);
    await refresh();
  } catch (exc) { if (alive) error.value = exc.message; }
  if (alive) timer = setInterval(() => { if (!document.hidden && !saving.value) refresh(); }, 5000);
});
onBeforeUnmount(() => { alive = false; sequence += 1; stateSequence += 1; clearInterval(timer); });
</script>

<style scoped>
.gitlab-workspace{display:grid;gap:16px;min-width:0}.gitlab-intro,.gitlab-settings,.gitlab-empty,.gitlab-update-list,.gitlab-review{padding:20px;min-width:0}.gitlab-heading,.gitlab-binding-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.gitlab-heading h2,.gitlab-heading h3{margin:0 0 8px}.gitlab-actions,.gitlab-status,.gitlab-badges,.gitlab-filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.gitlab-status{margin-top:14px}.gitlab-warnings{padding-left:22px;color:var(--muted);line-height:1.7}.gitlab-settings summary{cursor:pointer;font-weight:600}.gitlab-settings form{margin-top:18px}.gitlab-settings fieldset{border:0;padding:0;margin:0;min-width:0}.gitlab-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.gitlab-settings label{display:grid;gap:7px;min-width:0;font-size:13px}.gitlab-settings .input,.gitlab-settings .select{width:100%;min-width:0}.gitlab-options{margin:18px 0}.gitlab-options label{display:flex;align-items:center}.gitlab-baseline{display:grid;gap:8px;margin:20px 0}.gitlab-baseline .input{flex:1;min-width:160px}.gitlab-binding{display:grid;grid-template-columns:minmax(140px,1fr) minmax(160px,1fr) minmax(180px,1.4fr) auto;gap:10px;align-items:end;margin:12px 0}.gitlab-review-layout{display:grid;grid-template-columns:minmax(240px,300px) minmax(0,1fr);gap:16px;align-items:start}.gitlab-update-list{display:grid;gap:10px}.gitlab-update-row{display:grid;gap:8px;text-align:left;background:transparent;color:inherit;border:1px solid var(--line);border-radius:12px;padding:14px;cursor:pointer;overflow-wrap:anywhere}.gitlab-update-row.selected{border-color:var(--brand);background:rgba(204,168,87,.09)}.gitlab-row-title{font-weight:600}.gitlab-shas{display:grid;gap:6px;margin:16px 0;font-size:12px;overflow-wrap:anywhere}.gitlab-commits{padding-left:18px;line-height:1.8;overflow-wrap:anywhere}.gitlab-file-layout{display:grid;grid-template-columns:minmax(160px,220px) minmax(0,1fr);gap:14px;margin-top:18px}.gitlab-files{display:grid;align-content:start;gap:7px;max-height:600px;overflow:auto}.gitlab-files .btn{display:grid;gap:5px;text-align:left;white-space:normal;overflow-wrap:anywhere}.gitlab-files .btn[aria-pressed=true]{border-color:var(--brand)}.gitlab-diff{min-width:0}.gitlab-diff pre{margin:0;max-height:650px;overflow:auto;padding:14px;border:1px solid var(--line);border-radius:10px;background:rgba(0,0,0,.25);font-size:12px;line-height:1.7;tab-size:4}.diff-add{color:#9ad7ac}.diff-delete{color:#edaaa1}.gitlab-empty{padding:30px}.gitlab-empty h3{margin-top:0}.gitlab-review details{margin:12px 0}
.gitlab-workspace .badge{display:inline-flex;align-items:center;padding:3px 8px;border-radius:999px;border:1px solid var(--line);background:var(--chip-bg);color:var(--muted-strong);font-size:12px}.gitlab-files .btn{justify-content:stretch}
@media(max-width:1200px){.gitlab-review-layout{grid-template-columns:1fr}.gitlab-update-list{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.gitlab-filters{grid-column:1/-1}.gitlab-binding{grid-template-columns:1fr 1fr}}
@media(max-width:650px){.gitlab-form-grid,.gitlab-binding,.gitlab-file-layout{grid-template-columns:1fr}.gitlab-heading{flex-direction:column}.gitlab-intro,.gitlab-settings,.gitlab-review,.gitlab-update-list{padding:15px}.gitlab-files{max-height:220px}.gitlab-shas code{word-break:break-all}.gitlab-actions .btn{white-space:normal}.gitlab-binding-head{flex-wrap:wrap}}
</style>
