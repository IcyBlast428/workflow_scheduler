<template>
  <section class="gitlab-task-changes" :class="{'is-compact':!newTasks.length && !error && !state.error}" aria-label="GitLab 任务变更">
    <div class="changes-heading"><div><strong>GitLab 任务变更</strong><p class="hint">{{ state.enabled ? '目标分支合并后，可在此审查并发布。已发布任务的更新与删除标记在下方列表。' : '配置 GitLab 后，新任务会在首页置顶展示。' }}</p></div><button class="btn" :disabled="loading" @click="refresh">{{ loading ? '检查中…' : '刷新列表' }}</button><button v-if="canConfigure" class="btn" :disabled="scanning || !state.enabled" @click="scan">{{ scanning ? '已请求检查…' : '立即检查 GitLab' }}</button><button v-if="canConfigure" class="btn" @click="$emit('settings')">连接设置</button></div>
    <p v-if="newTasks.length || error || state.error" class="hint">最近完成检查：{{ state.checked_at || '尚未检查' }} · {{ state.complete ? '扫描完整' : '等待检查或结果不完整' }}</p>
    <p v-if="error || state.error" class="inline-alert warning" role="alert">{{ error || state.error }}</p>
    <div v-if="firstPage && newTasks.length" class="new-task-grid">
      <article v-for="item in newTasks" :key="item.id" class="new-task-card"><div><span class="tag success">GitLab 新任务 · 待发布</span><h3>{{ item.task_name }}</h3><p class="hint">{{ item.group_name }} / {{ item.folder_name }}</p><small class="mono">{{ item.sha.slice(0, 8) }} · {{ item.file_count }} 个文件</small><p v-if="item.error" class="danger-text">{{ item.error }}</p></div><button class="btn primary" :disabled="item.blocked" @click="$emit('open', item.pid)">审查并发布</button></article>
    </div>
    <p v-else-if="!firstPage && newTasks.length" class="hint">有 {{ newTasks.length }} 个新任务待发布，请返回任务列表首页查看。</p>
    <p v-else-if="state.enabled && state.complete && !state.items.length" class="hint">已发布任务与 GitLab 一致。</p>
  </section>
</template>
<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { api } from '../api';
const props=defineProps({ firstPage: Boolean,canConfigure:{type:Boolean,default:true} });
const emit = defineEmits(['state', 'open', 'settings']);
const state = ref({ enabled: false, items: [] }), error = ref(''), loading = ref(false);
const newTasks = computed(() => state.value.items.filter(item => item.kind === 'new'));
const scanning = ref(false);
async function scan() { scanning.value = true; try { await api.scanGitlab(); await refresh(); } catch(err) { error.value = err.message; scanning.value = false; } }
let alive = true, timer, sequence = 0;
async function refresh() {
  const token = ++sequence; loading.value = true;
  try { const [data, scanState] = await Promise.all([api.gitlabTasks(), props.canConfigure ? api.gitlabState(true) : Promise.resolve({scanning:false})]); if (alive && token === sequence) { state.value = data; scanning.value = scanState.scanning; error.value = ''; emit('state', data); } }
  catch (err) { if (alive && token === sequence) { error.value = err.message; emit('state', { items: [] }); } }
  finally { if (alive && token === sequence) loading.value = false; }
}
onMounted(() => { refresh(); timer = setInterval(() => { if (!document.hidden) refresh(); }, 15000); window.addEventListener('wfs:task-releases-refresh', refresh); });
onBeforeUnmount(() => { alive = false; sequence++; clearInterval(timer); window.removeEventListener('wfs:task-releases-refresh', refresh); });
</script>
<style scoped>
.gitlab-task-changes.is-compact{padding:12px 20px}.is-compact .changes-heading p{font-size:12px;margin-bottom:0}.is-compact .changes-heading .btn{padding:7px 10px}.gitlab-task-changes{padding:22px;border-bottom:1px solid var(--line)}.changes-heading{display:flex;align-items:center;gap:12px}.changes-heading>div{flex:1;min-width:0}.changes-heading p{margin-top:8px;line-height:1.6}.new-task-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-top:20px}.new-task-card{display:flex;gap:18px;align-items:center;justify-content:space-between;padding:20px;border:1px solid #448a78;border-radius:var(--radius);background:linear-gradient(125deg,#66c9a018,transparent)}.new-task-card h3{margin:14px 0 8px}.new-task-card small{display:block;margin-top:10px;overflow-wrap:anywhere}.new-task-card>div{min-width:0}.new-task-card button{flex-shrink:0}.gitlab-task-changes>p{margin-top:16px}@media(max-width:720px){.changes-heading{flex-wrap:wrap}.changes-heading>div{flex-basis:100%}.new-task-grid{grid-template-columns:1fr}.new-task-card{flex-wrap:wrap}}
</style>
