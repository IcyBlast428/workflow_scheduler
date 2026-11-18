<template>
  <section class="gitlab-task-changes changes-summary" aria-label="GitLab 任务变更">
    <div class="changes-status" role="status">
      <strong>GitLab</strong>
      <span class="tag" :class="checkError ? 'warning' : 'info'">{{ connectionStatus }}</span>
      <span v-if="pendingTasks.length" class="tag warning">{{ pendingTasks.length }} 项待处理</span>
    </div>
    <button class="btn" type="button" aria-haspopup="dialog" @click="open = true">查看连接与检查状态</button>
  </section>

  <Teleport to="body">
    <ModalShell :open="open" label="GitLab 连接与检查状态" panel-class="gitlab-changes-modal" @close="open = false">
      <header class="modal-head">
        <h3>GitLab 连接与检查状态</h3>
        <button class="btn icon-only" type="button" aria-label="关闭" @click="open = false">×</button>
      </header>
      <div class="modal-body changes-content">
        <div class="changes-heading">
          <div>
            <strong>{{ connectionStatus }}</strong>
            <p v-if="state.enabled" class="hint">最近完成检查：{{ scanTime }} · {{ state.complete ? '扫描完整' : '等待检查或结果不完整' }}</p>
            <p v-else-if="loaded" class="hint">配置 GitLab 后，可在此审查新增、更新、恢复和删除变更。</p>
          </div>
          <div class="filter-actions">
            <button class="btn" type="button" :disabled="loading" @click="refresh">{{ loading ? '检查中…' : '刷新列表' }}</button>
            <button v-if="canConfigure" class="btn" type="button" :disabled="loading || scanning || !state.enabled" @click="scan">{{ scanning ? '已请求检查…' : '立即检查 GitLab' }}</button>
            <button v-if="canConfigure" class="btn" type="button" @click="openSettings">连接设置</button>
          </div>
        </div>
        <p v-if="checkError" class="inline-alert warning" role="alert">{{ checkError }}</p>
        <div v-if="pendingTasks.length" class="new-task-grid">
          <article v-for="item in pendingTasks" :key="item.id" class="new-task-card">
            <div>
              <span class="tag" :class="item.kind === 'delete' ? 'danger' : item.kind === 'new' ? 'success' : 'warning'">{{ changeLabels[item.kind] || '任务变更 · 待处理' }}</span>
              <h4>{{ item.recovery?.task_name || item.task_name }}</h4>
              <p v-if="item.recovery" class="hint">保留原任务编号 {{ item.recovery.pid }}、调度配置和历史记录。</p>
              <p class="hint">{{ item.group_name }} / {{ item.folder_name }}</p>
              <small class="mono">{{ item.sha.slice(0, 8) }} · {{ item.file_count }} 个文件</small>
              <p v-if="item.error" class="danger-text">{{ item.error }}</p>
            </div>
            <button class="btn primary" type="button" :disabled="item.blocked" @click="openTask(item.pid)">
              {{ item.kind === 'recover' ? '恢复原任务' : item.kind === 'delete' ? '查看删除变更' : '审查并发布' }}
            </button>
          </article>
        </div>
        <p v-else-if="state.enabled && state.complete && !checkError" class="hint">已发布任务与 GitLab 一致。</p>
      </div>
    </ModalShell>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref } from 'vue';
import ModalShell from './ModalShell.vue';
import { useRefreshLoop } from '../composables/useRefreshLoop.js';
import { api } from '../api';

const props = defineProps({ canConfigure: { type: Boolean, default: true } });
const emit = defineEmits(['state', 'open', 'settings']);
const changeLabels = {
  new: '新任务 · 待发布',
  recover: '原任务 · 待恢复关联',
  update: '原任务 · 待更新',
  delete: '原任务 · 待确认删除',
};
const state = ref({ enabled: false, items: [] });
const open = ref(false);
const error = ref('');
const loading = ref(false);
const loaded = ref(false);
const scanning = ref(false);
const pendingTasks = computed(() => state.value.items || []);
const checkError = computed(() => error.value || state.value.error);
const connectionStatus = computed(() => {
  if (checkError.value) return '检查异常';
  if (!loaded.value) return '正在读取状态…';
  if (!state.value.enabled) return '未连接';
  return scanning.value ? '检查中' : '已配置连接';
});
const scanTime = computed(() => state.value.checked_at
  ? new Date(state.value.checked_at * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
  : '尚未检查');

function openSettings() {
  open.value = false;
  emit('settings');
}

async function openTask(pid) {
  open.value = false;
  await nextTick();
  emit('open', pid);
}

async function scan() {
  scanning.value = true;
  try {
    await api.scanGitlab();
    await refresh();
  } catch (err) {
    error.value = err.message;
    scanning.value = false;
  }
}

let alive = true;
let pending = null;
function refresh() {
  if (pending) return pending;
  pending = fetchChanges().finally(() => { pending = null; });
  return pending;
}

async function fetchChanges() {
  loading.value = true;
  try {
    const [data, scanState] = await Promise.all([
      api.gitlabTasks(),
      props.canConfigure ? api.gitlabState(true) : Promise.resolve({ scanning: false }),
    ]);
    if (!alive) return;
    state.value = data;
    scanning.value = scanState.scanning;
    error.value = '';
    loaded.value = true;
    emit('state', data);
  } catch (err) {
    if (alive) {
      error.value = err.message;
      emit('state', { items: [] });
    }
    return false;
  } finally {
    if (alive) loading.value = false;
  }
}

useRefreshLoop({ load: refresh, interval: 15000 });
onMounted(() => window.addEventListener('wfs:task-releases-refresh', refresh));
onBeforeUnmount(() => {
  alive = false;
  window.removeEventListener('wfs:task-releases-refresh', refresh);
});
</script>

<style scoped>
.changes-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 16px;
  padding: 10px var(--panel-padding);
  border-top: 1px solid var(--line);
}
.changes-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 13px;
}
.changes-heading {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.changes-heading p { margin: 6px 0 0; }
.changes-content > p { margin: 12px 0 0; }
.new-task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
  gap: 12px;
  margin-top: 16px;
}
.new-task-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel);
}
.new-task-card > div { min-width: 0; overflow-wrap: anywhere; }
.new-task-card h4 { margin: 8px 0 0; }
.new-task-card p { margin: 4px 0 0; }
.new-task-card small { display: block; margin-top: 6px; }
</style>
