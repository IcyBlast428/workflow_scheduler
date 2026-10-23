<template>
  <CursorLight />
  <div v-if="!ready" class="boot-screen">
    <div class="boot-card">
      <BrandLogo class="boot-mark" />
      <div class="boot-copy">
        <strong>定时任务调度</strong>
        <span>{{ backendStatus.message }}</span>
        <button
          v-if="backendStatus.error"
          class="btn"
          type="button"
          @click="retryBootstrap"
        >
          重新检测
        </button>
      </div>
    </div>
  </div>

  <main
    v-else-if="!token"
    class="login-screen"
    :style="{ '--login-radius': `${LOGIN_CORNER_RADIUS}px` }"
  >
    <LoginBackdrop @scene-change="loginVisual = $event" />
    <LiquidGlassPanel :snapshot="loginVisual">
      <div class="login-brief">
        <div class="login-brand-row">
          <BrandLogo /><span>WORKFLOW SCHEDULER</span>
        </div>
        <h1>定时任务调度</h1>
        <p>使用已分配的账户登录，系统会根据账户权限进入相应工作区。</p>
        <div class="login-workflow" aria-hidden="true">

          <div class="login-workflow-step">
            <span
              ><svg viewBox="0 0 24 24" fill="none">
                <rect x="4" y="4" width="6" height="6" rx="1.5" />
                <rect x="14" y="4" width="6" height="6" rx="1.5" />
                <rect x="9" y="14" width="6" height="6" rx="1.5" />
                <path d="M7 10v2h10v-2M12 12v2" /></svg></span
            ><strong>编排</strong><small>组织任务</small>
          </div>
          <div class="login-workflow-step">
            <span
              ><svg viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="8" />
                <path d="M12 7v5l-3 2" /></svg></span
            ><strong>调度</strong><small>按时触发</small>
          </div>
          <div class="login-workflow-step">
            <span
              ><svg viewBox="0 0 24 24" fill="none">
                <path d="m7 12 3 3 7-7" />
                <rect x="4" y="4" width="16" height="16" rx="4" /></svg></span
            ><strong>执行</strong><small>记录结果</small>
          </div>
        </div>

      </div>
      <form class="login-form" @submit.prevent="handleLogin">
        <div class="login-form-head">
          <div>
            <h2>登录工作区</h2>
            <p class="hint">管理员和普通用户使用同一个登录入口。</p>
          </div>
        </div>
        <div v-if="backendStatus.error" class="inline-alert danger">
          <strong>后端未连接</strong>
          <span>{{ backendStatus.error }}</span>
          <button class="btn" type="button" @click="checkBackend()">
            重试
          </button>
        </div>
        <div
          v-else
          class="inline-alert"
          :class="backendStatus.ready ? 'login-ready' : 'warning'"
        >
          <strong>{{
            backendStatus.ready ? '服务已就绪' : '接口已连接，服务尚未就绪'
          }}</strong>
          <span>{{ backendStatus.message }}</span>
        </div>
        <div class="form-row">
          <label for="username">用户名</label>
          <input
            id="username"
            v-model.trim="loginForm.username"
            class="input"
            autocomplete="username"
            required
          />
        </div>
        <div class="form-row">
          <label for="password">密码</label>
          <input
            id="password"
            v-model="loginForm.password"
            class="input"
            type="password"
            autocomplete="current-password"
            required
          />
        </div>
        <button
          class="btn primary"
          type="submit"
          aria-label="登录"
          :disabled="loginLoading || !backendStatus.reachable"
        >
          <span class="btn-icon">></span>
          {{ loginLoading ? '登录中...' : '登录' }}
        </button>

      </form>
    </LiquidGlassPanel>
  </main>

  <div v-else class="app-shell" :class="{ 'nav-expanded': navExpanded }">
    <aside class="sidebar" :class="{ open: mobileNavOpen }">
      <div class="brand">
        <BrandLogo />
        <div class="brand-copy">
          <h1>{{ user.project || '定时任务调度' }}</h1>
          <span>Workflow Scheduler</span>
        </div>
      </div>
      <button
        class="btn sidebar-toggle"
        type="button"
        :aria-expanded="navExpanded"
        aria-controls="workspace-navigation"
        :aria-label="navExpanded ? '收起导航' : '展开导航'"
        @click="navExpanded = !navExpanded"
      >
        <span aria-hidden="true">{{ navExpanded ? '‹' : '›' }}</span
        ><span v-if="navExpanded">收起导航</span>
      </button>
      <button
        class="btn icon-only mobile-menu"
        type="button"
        title="菜单"
        @click="mobileNavOpen = !mobileNavOpen"
      >
        ≡
      </button>
      <nav id="workspace-navigation" class="nav" aria-label="工作区导航">
        <button
          v-glass
          v-for="item in visibleNavItems"
          :key="item.id"
          class="nav-button"
          :class="{ active: view === item.id }"
          type="button"
          :title="item.label"
          :aria-label="item.label"
          :aria-current="view === item.id ? 'page' : undefined"
          @mouseenter="showNavHint(item, $event)"
          @mouseleave="navHint = null"
          @focus="showNavHint(item, $event)"
          @blur="navHint = null"
          @click="
            navHint = null;
            switchView(item.id);
          "
        >
          <span class="nav-icon" aria-hidden="true">
            <svg class="nav-svg" viewBox="0 0 24 24" role="img">
              <path v-for="path in item.iconPaths" :key="path" :d="path" />
            </svg>
          </span>
          <span class="nav-label">{{ item.label }}</span>
        </button>
      </nav>
      <div class="sidebar-account">
        <UserMenu
          placement="sidebar"
          :name="user.name || 'Admin'"
          :avatar="user.avatar"
          @logout="handleLogout"
        />
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="page-title">
          <strong>{{ activeNav.label }}</strong>
          <span>{{ canManage ? activeNav.description : '用户工作区 · 只读查看任务' }}</span>
        </div>
        <div class="top-actions">
          <button
            class="btn effects-toggle"
            :aria-pressed="lowEffects"
            @click="lowEffects = !lowEffects"
          >
            {{ lowEffects ? '恢复特效' : '简化特效' }}
          </button>
          <ServiceStatus :status="backendStatus" />

        </div>
      </header>

      <section
        class="content"
        :class="{ 'dashboard-content': view === 'dashboard' }"
      >
        <div
          v-if="backendStatus.error"
          class="inline-alert danger content-alert"
        >
          <strong>当前后端连接异常</strong>
          <span>{{ backendStatus.error }}</span>
          <button class="btn" type="button" @click="refreshActiveView()">
            重新检测
          </button>
        </div>

        <template v-if="view === 'dashboard'">
          <DashboardView
            :dashboard="dashboard"
            :can-manage="canManage"
            @detail="detailPid = $event"
            @execution="openExecution"
            @admin="switchView('admin')"
            @tasks="showFilteredTasks"
          />
        </template>

        <template v-else-if="view === 'matrix'">
          <ExecutionMatrix
            :user-key="user.name"
            @task="detailPid = $event"
            @execution="openExecution"
            @logs="openMatrixLogs"
          />
        </template>

        <template v-else-if="view === 'tasks'">
          <TaskWorkspaceView
            :tasks="tasks"
            :selected-tasks="selectedTasks"
            :favorites="favorites"
            :only-favorites="onlyFavorites"
            :batch-busy="batchBusy"
            :busy="busy"
            :pending-actions="pendingActions"
            :can-manage="canManage"
            :can-operate="canOperate"
            @search="loadTasks(true)"
            @reset="resetTaskFilters"
            @page="setTaskPage"
            @page-size="setTaskPageSize"
            @batch="batchTaskAction"
            @clear-selection="selectedTasks = []"
            @packages="openPackages('')"
            @favorite="toggleFavorite"
            @select="toggleSelected"
            @detail="detailPid = $event"
            @execution="openActiveExecution"
            @action="editTask"
            @pause="pauseTask"
            @call="handleCallTask"
            @schedule="openScheduleDialog"
            @log="openLatestLog"
            @favorites-only="
              onlyFavorites = $event;
              loadTasks(true);
            "
          />
        </template>

        <template v-else-if="view === 'taskLogs'">
          <ExecutionLogsView
            :task-logs="taskLogs"
            :matrix-log-range="matrixLogRange"
            @range="setLogRange"
            @search="searchTaskLogs"
            @reset="resetTaskLogFilters"
            @open="openTaskLog"
            @page="setTaskLogPage"
            @page-size="setTaskLogPageSize"
          />
        </template>

        <template v-else-if="view === 'packages' && canManage"
          ><TaskPackageManager
            :confirm="requestConfirm"
            :initial-pid="packagePid"
            @detail="detailPid = $event"
            @changed="refreshPackageTasks"
        /></template>
        <template v-else-if="view === 'admin' && canManage"
          ><AdminPanel
        /></template>
        <template v-else-if="view === 'connections' && canManage"><DatabaseConnections :confirm="requestConfirm" /></template>
        <template v-else-if="canManage">
          <SystemEventsView
            :system-logs="systemLogs"
            @search="loadSystemLogs(true)"
            @reset="resetSystemLogFilters"
            @open="
              (row) => showModal('平台事件：' + row.id, row.systeminfo || ' ')
            "
            @page="setSystemLogPage"
            @page-size="setSystemLogPageSize"
          />
        </template>
      </section>
    </div>
  </div>

  <ModalShell :open="modal.open" :label="modal.title" @close="closeModal">
    <header class="modal-head">
      <h3>{{ modal.title }}</h3>
      <div class="modal-actions">
        <button class="btn" type="button" @click="toggleWrap">
          {{ modal.wrap ? '单行滚动' : '自动换行' }}
        </button>
        <button class="btn" type="button" @click="copyModalContent">
          复制内容
        </button>
        <button
          class="btn icon-only"
          type="button"
          title="关闭"
          @click="closeModal"
        >
          ×
        </button>
      </div>
    </header>
    <div class="modal-body">
      <pre class="log-pre" :class="{ nowrap: !modal.wrap }">{{
        modal.content
      }}</pre>
    </div>
  </ModalShell>

  <Teleport to="body"
    ><div
      v-if="navHint"
      class="nav-tooltip"
      :style="{ left: `${navHint.left}px`, top: `${navHint.top}px` }"
      aria-hidden="true"
    >
      {{ navHint.label }}
    </div></Teleport
  >
  <div class="toast-root" aria-live="polite">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      v-glass
      class="toast glass-surface glass-floating"
      :class="toast.type"
    >
      <strong>{{ toast.title }}</strong>
      <span>{{ toast.message }}</span>
    </div>
  </div>

  <ConfirmDialog :model-value="confirmState" @resolve="resolveConfirm" />
  <TaskDetailDialog
    :pid="detailPid"
    :can-manage="canManage"
    @close="detailPid = ''"
    @execution="openExecution"
    @confirm-restore="confirmRestore"
    @packages="openPackages"
  />
  <ExecutionDialog
    :run-id="executionRunId"
    :can-operate="canOperate"
    :retrying="retryingExecution"
    @retry="retryExecution"
    @close="executionRunId = ''"
  />
  <ScheduleDialog
    :open="scheduleDialog.open"
    :loading="scheduleDialog.loading"
    :saving="scheduleDialog.saving"
    :error="scheduleDialog.error"
    :preview="scheduleDialog.preview"
    :preview-loading="scheduleDialog.previewLoading"
    :preview-error="scheduleDialog.previewError"
    :task="scheduleDialog.task"
    :schedule="scheduleDialog.data"
    @close="closeScheduleDialog"
    @save="saveSchedule"
    @reload="openScheduleDialog(scheduleDialog.task)"
    @preview="previewSchedule"
  />
</template>

<script setup>
import ServiceStatus from './components/ServiceStatus.vue';
import DashboardView from './views/DashboardView.vue';
import TaskWorkspaceView from './views/TaskWorkspaceView.vue';
import ExecutionLogsView from './views/ExecutionLogsView.vue';
import SystemEventsView from './views/SystemEventsView.vue';
import { useBackendStatus } from './composables/useBackendStatus';
import { useLiveUpdates } from './composables/useLiveUpdates';

import {
  defineAsyncComponent,
  computed,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  shallowRef,
  watch,
} from 'vue';
import ModalShell from './components/ModalShell.vue';
import { readPreference, writePreference } from './workspacePreferences';
import { readRoute, routeHash } from './routeLocation';
import BrandLogo from './components/BrandLogo.vue';
import CursorLight from './components/CursorLight.vue';
import LoginBackdrop from './components/LoginBackdrop.vue';
import LiquidGlassPanel from './components/LiquidGlassPanel.vue';
import { LOGIN_CORNER_RADIUS } from './loginBackdropScene';
import UserMenu from './components/UserMenu.vue';
import { api, clearToken, getToken, setToken } from './api';
import { scheduleRequest } from './scheduleForm';
import ConfirmDialog from './components/ConfirmDialog.vue';
import ScheduleDialog from './components/ScheduleDialog.vue';
import { useTaskWorkspace } from './composables/useTaskWorkspace';
import { useLogWorkspace } from './composables/useLogWorkspace';
import { useDashboardWorkspace } from './composables/useDashboardWorkspace';
import TaskDetailDialog from './components/TaskDetailDialog.vue';
import ExecutionDialog from './components/ExecutionDialog.vue';
const AdminPanel = defineAsyncComponent(
  () => import('./components/AdminPanel.vue'),
);
const DatabaseConnections = defineAsyncComponent(() => import('./components/DatabaseConnections.vue'));
const TaskPackageManager = defineAsyncComponent(
  () => import('./components/TaskPackageManager.vue'),
);
const ExecutionMatrix = defineAsyncComponent(
  () => import('./components/ExecutionMatrix.vue'),
);
import { canTrigger } from './executionLabels';
import { useConfirm } from './composables/useConfirm';
const loginVisual = shallowRef(null);
const lowEffects = ref(Boolean(readPreference('wfs:low-effects', false)));
watch(
  lowEffects,
  (value) => {
    document.documentElement.dataset.effects = value ? 'low' : 'full';
    writePreference('wfs:low-effects', value);
    window.dispatchEvent(new Event('wfs:effects'));
  },
  { immediate: true },
);
const navHint = ref(null);
const navExpanded = ref(Boolean(readPreference('wfs:nav-expanded', true)));
watch(navExpanded, (value) => writePreference('wfs:nav-expanded', value));
function showNavHint(item, event) {
  if (navExpanded.value) return;
  const rect = event.currentTarget.getBoundingClientRect();
  navHint.value = {
    label: item.label,
    top: rect.top + rect.height / 2,
    left: rect.right + 10,
  };
}

const navItems = [
  {
    id: 'dashboard',
    label: '总览',
    iconPaths: [
      'M4 13.5a8 8 0 1 1 16 0',
      'M8 15h8',
      'M12 15l3.4-5.8',
      'M7 19h10',
    ],
    description: 'CPU、内存与任务运行关系。',
  },
  {
    id: 'tasks',
    label: '任务列表',
    iconPaths: [
      'M4.5 6.5h15',
      'M4.5 12h15',
      'M4.5 17.5h15',
      'M8 4.5v4',
      'M16 10v4',
      'M11 15.5v4',
    ],
    description: '已发布任务、调度状态与运行控制。',
  },
  {
    id: 'matrix',
    label: '执行矩阵',
    iconPaths: ['M3 7l9-4 9 4-9 4z', 'M3 12l9 4 9-4', 'M3 17l9 4 9-4'],
    description: '按任务分类查看当日执行轨迹。',
  },
  {
    id: 'taskLogs',
    label: '执行记录',
    iconPaths: [
      'M7 4.5h7l3 3v12H7z',
      'M14 4.5v4h4',
      'M9.5 12h5',
      'M9.5 15.5h5',
    ],
    description: '脚本执行历史与输出摘要。',
  },
  {
    id: 'systemLogs',
    label: '平台事件',
    iconPaths: ['M12 3.8l7 4v8.4l-7 4-7-4V7.8z', 'M12 8v5', 'M12 16.3v.2'],
    description: '调度器事件与系统异常记录。',
  },
  {
    id: 'packages',
    label: '任务发布',
    iconPaths: ['M3 7l9-4 9 4-9 4z', 'M3 7v10l9 4 9-4V7', 'M12 11v10'],
    description: '任务包上传、发布、版本回滚与回收站。',
  },
  {
    id: 'admin',
    label: '账户与审计',
    iconPaths: ['M4 6h16', 'M4 12h16', 'M4 18h16'],
    description: '账户权限与操作记录。',
  },
  {id: 'connections', label: '数据库连接', iconPaths: ['M4 6c0-4 16-4 16 0s-16 4-16 0','M4 6v12c0 4 16 4 16 0V6','M4 12c0 4 16 4 16 0'], description: '平台与任务业务数据库连接设置。'},
];

const ready = ref(false);
const token = ref(getToken());
const view = ref(readRoute(window.location.hash).view);
const packagePid = ref('');
const mobileNavOpen = ref(false);
const loginLoading = ref(false);
const busy = ref(false);
const pendingActions = reactive({});
const retryingExecution = ref(false);
const detailPid = ref('');
const executionRunId = ref('');
const toasts = ref([]);
const { confirmState, requestConfirm, resolveConfirm } = useConfirm();

let scheduleLoadSeq = 0;
let schedulePreviewSeq = 0;

const {
  backendStatus,
  markBackendHealthy,
  checkBackend: probeBackend,
} = useBackendStatus();

const loginForm = reactive({
  username: '',
  password: '',
});


const user = reactive({
  project: '',
  name: '',
  avatar: '',
  roles: [],
});
const canManage = computed(() => user.roles.includes('admin'));
const canOperate = computed(() => canManage.value);
const visibleNavItems = computed(() =>
  navItems.filter(
    (item) => canManage.value || ['tasks', 'matrix', 'taskLogs'].includes(item.id),
  ),
);

const {
  tasks,
  favorites,
  onlyFavorites,
  selectedTasks,
  batchBusy,
  toggleFavorite,
  toggleSelected,
  loadTasks,
  loadGroups,
  resetTaskFilters,
  setTaskPage,
  setTaskPageSize,
  batchTaskAction,
} = useTaskWorkspace(() => user.name, {
  markBackendHealthy,
  handleRequestFailure,
  requestConfirm,
  pushToast,
});

const { dashboard, loadDashboard, syncDashboardPolling } =
  useDashboardWorkspace({
    token,
    view,
    markBackendHealthy,
    handleRequestFailure,
  });
const {
  taskLogs,
  systemLogs,
  matrixLogRange,
  loadTaskLogs,
  loadTaskIds,
  resetTaskLogFilters,
  setLogRange,
  searchTaskLogs,
  setTaskLogPage,
  setTaskLogPageSize,
  loadSystemLogs,
  loadSystemIds,
  resetSystemLogFilters,
  setSystemLogPage,
  setSystemLogPageSize,
} = useLogWorkspace({ markBackendHealthy, handleRequestFailure, syncRoute });
const { startLiveEvents, stopLiveEvents } = useLiveUpdates({
  token,
  view,
  tasks,
  taskLogs,
  loadTasks,
  loadTaskLogs,
  markBackendHealthy,
  handleRequestFailure,
});
let logDetailSerial = 0;

const modal = reactive({
  open: false,
  title: '',
  content: '',
  wrap: true,
});

const scheduleDialog = reactive({
  open: false,
  loading: false,
  saving: false,
  error: '',
  preview: [],
  previewLoading: false,
  previewError: '',
  task: null,
  data: null,
});

const activeNav = computed(
  () => navItems.find((item) => item.id === view.value) || navItems[0],
);

function pushToast(type, title, message) {
  const id = Date.now() + Math.random();
  toasts.value.push({ id, type, title, message: String(message || '') });
  window.setTimeout(() => {
    toasts.value = toasts.value.filter((toast) => toast.id !== id);
  }, 4200);
}

function isAuthError(error) {
  return String(error?.code) === '50008';
}

async function handleRequestFailure(error, options = {}) {
  if (isAuthError(error)) {
    clearToken();
    token.value = '';
    pushToast('error', '会话已失效', '登录状态已过期，请重新登录。');
    return true;
  }

  if (
    error?.code === 'NETWORK_ERROR' ||
    error?.code === 'INVALID_JSON_RESPONSE'
  ) {
    backendStatus.reachable = false;
    backendStatus.error = error.message;
    backendStatus.message = error.message;
  } else if (String(error?.code || '').startsWith('HTTP_5')) {
    probeBackend();
  }

  if (options.state) {
    options.state.error = error.message;
  }
  if (options.toastTitle) {
    pushToast('error', options.toastTitle, error.message);
  }
  return false;
}

async function checkBackend(options = {}) {
  const reachable = await probeBackend();
  if (!reachable && !options.silent)
    pushToast('error', '后端不可达', backendStatus.error);
  return reachable;
}

async function retryBootstrap() {
  const reachable = await checkBackend();
  if (reachable) {
    ready.value = true;
  }
}

function showModal(title, content) {
  modal.title = title;
  modal.content = formatModalContent(content);
  modal.wrap = true;
  modal.open = true;
}

function formatModalContent(content) {
  if (content === undefined || content === null || content === '') {
    return ' ';
  }
  if (typeof content === 'string') {
    return content;
  }
  try {
    return JSON.stringify(content, null, 2);
  } catch (error) {
    return String(content);
  }
}

function closeModal() {
  logDetailSerial++;
  modal.open = false;
}

function toggleWrap() {
  modal.wrap = !modal.wrap;
}

async function copyModalContent() {
  try {
    await navigator.clipboard.writeText(modal.content || '');
    pushToast('success', '复制成功', '日志内容已复制到剪贴板。');
  } catch (error) {
    pushToast('error', '复制失败', '当前环境不支持剪贴板写入。');
  }
}

function canCallTask(row) {
  return canTrigger(row);
}

function callTaskTitle(row) {
  if (row.state === 'invalid') {
    return '配置错误的任务不能手动触发';
  }
  if (!canTrigger(row)) {
    return '并发名额已满，请等待正在运行的实例结束';
  }
  if (row.state === 'pause') {
    return '暂停任务也可以手动执行一次';
  }
  if (row.state !== 'true') {
    return '任务未进入调度，也可以手动执行一次';
  }
  return '立即执行一次任务';
}

async function loadUser() {
  const data = await api.userInfo();
  markBackendHealthy('后端连接正常');
  user.project = data.project || '定时任务调度';
  user.name = data.name || 'Admin';
  user.avatar = data.avatar || '/static/img/head.gif';
  user.roles = data.roles || [];

  if (data.csrf_token) {
    setToken(data.csrf_token);
    token.value = data.csrf_token;
  }
  if (!canManage.value && !['tasks', 'matrix', 'taskLogs'].includes(view.value))
    switchView('tasks');
  const prefix = canManage.value ? '/admin/' : '/viewer/';
  window.history.replaceState(null, '', prefix + window.location.hash);
}

async function handleLogin() {
  const reachable = await checkBackend({ silent: true });
  if (!reachable) {
    pushToast('error', '登录失败', backendStatus.error);
    return;
  }

  loginLoading.value = true;
  try {
    const data = await api.login({ ...loginForm });
    loginForm.password = '';
    user.roles = data.role ? [data.role] : [];
    markBackendHealthy('后端连接正常');
    setToken(data.csrf_token);
    token.value = data.csrf_token;
    await loadUser();
    await Promise.all([...(canManage.value ? [loadDashboard()] : []), loadTasks(), loadGroups()]);
    startLiveEvents();
    applyRoute();
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '登录失败' });
  } finally {
    loginLoading.value = false;
  }
}

async function handleLogout() {

  try {
    await api.logout();
  } catch (error) {
    await handleRequestFailure(error);
  }
  clearToken();
  token.value = '';
  user.roles = [];
  detailPid.value = '';
  executionRunId.value = '';
  scheduleDialog.open = false;
  scheduleDialog.data = null;
  closeModal();
  stopLiveEvents();
}

function switchView(nextView) {
  if (token.value && !canManage.value && !['tasks', 'matrix', 'taskLogs'].includes(nextView)) nextView = 'tasks';
  view.value = nextView;
  window.location.hash = nextView;
  mobileNavOpen.value = false;
  syncDashboardPolling();
}

function openPackages(pid) {
  detailPid.value = '';
  packagePid.value = pid;
  switchView('packages');
}
async function refreshPackageTasks() {
  await Promise.all([loadTasks(), loadGroups()]);
}

async function refreshActiveView() {
  const reachable = await checkBackend({ silent: true });
  if (!reachable) {
    pushToast('error', '刷新失败', backendStatus.error);
    return;
  }

  if (view.value === 'dashboard') {
    await loadDashboard();
  } else if (view.value === 'tasks') {
    await Promise.all([loadTasks(), loadGroups()]);
  } else if (view.value === 'taskLogs') {
    await Promise.all([loadTaskLogs(), loadTaskIds()]);
  } else if (view.value === 'matrix') {
    window.dispatchEvent(new Event('wfs:matrix-refresh'));
  } else if (view.value === 'packages') {
    window.dispatchEvent(new Event('wfs:packages-refresh'));
  } else {
    await Promise.all([loadSystemLogs(), loadSystemIds()]);
  }
}

async function editTask(row, state) {
  if (state === 'kill') {
    const confirmed = await requestConfirm({
      title: `强制停止任务 ${row.id}`,
      message: '该操作会终止正在运行的任务进程，并将任务加入暂停列表。',
      details: [
        `任务名称：${row.name}`,
        `组名：${row.group_name || '-'}`,
        '如果脚本正在写入数据，请确认它具备幂等或补偿能力。',
      ],
      confirmText: '强制停止',
      danger: true,
    });
    if (!confirmed) {
      return;
    }
  }
  pendingActions[row.id] = state;
  try {
    const message = await api.editTask({
      id: row.id,
      state,
    });
    markBackendHealthy('后端连接正常');
    pushToast('success', '操作成功', message);
    await loadTasks();
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '操作失败' });
  } finally {
    delete pendingActions[row.id];
  }
}

async function handleCallTask(row) {
  if (!canCallTask(row)) {
    pushToast('error', '无法触发任务', callTaskTitle(row));
    return;
  }
  pendingActions[row.id] = true;
  try {
    const message = await api.callTask({ pid: row.id });
    markBackendHealthy('后端连接正常');
    pushToast('success', '任务已排队', message.message || message);
    if (message.run_id) openExecution(message.run_id);
    const refreshes = [loadTasks()];
    if (view.value === 'taskLogs' && taskLogs.params.currentPage === 1) {
      refreshes.push(loadTaskLogs(false, { silent: true }));
    }
    await Promise.all(refreshes);
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '任务触发失败' });
  } finally {
    delete pendingActions[row.id];
  }
}

async function pauseTask(row) {
  if (row.pending) {
    const confirmed = await requestConfirm({
      title: `任务 ${row.id} 正在执行`,
      message: '暂停只会移除后续调度；如果要立即停止当前进程，请选择强制停止。',
      details: [
        '选择“强制停止”会终止当前进程。',
        '选择“仅暂停”会保留当前执行；关闭窗口或选择“取消”不会执行操作。',
      ],
      confirmText: '强制停止',
      cancelText: '仅暂停',
      danger: true,
    });
    if (confirmed === null) return;
    if (confirmed) {
      editTask(row, 'kill');
      return;
    }
    editTask(row, 'pause');
    return;
  }
  editTask(row, 'pause');
}

async function openScheduleDialog(row) {
  const keepData =
    scheduleDialog.open &&
    scheduleDialog.task?.id === row.id &&
    scheduleDialog.data;
  const seq = ++scheduleLoadSeq;
  schedulePreviewSeq += 1;
  scheduleDialog.open = true;
  scheduleDialog.loading = true;
  scheduleDialog.saving = false;
  scheduleDialog.error = '';
  if (!keepData) scheduleDialog.preview = [];
  scheduleDialog.previewError = '';
  scheduleDialog.previewLoading = false;
  scheduleDialog.task = { ...row };
  if (!keepData) scheduleDialog.data = null;
  try {
    const data = await api.taskSchedule({
      pid: row.id,
    });
    if (seq !== scheduleLoadSeq || scheduleDialog.task?.id !== row.id) {
      return;
    }
    if (data.pid && data.pid !== row.id) {
      throw new Error(
        `后端返回 PID ${data.pid} 与当前任务 ${row.id} 不一致，请刷新页面后重试。`,
      );
    }
    scheduleDialog.task = {
      ...row,
      id: row.id,
      name: data.task_name || row.name,
      group_name: data.group_name || row.group_name || '',
      folder_name: data.folder_name || row.folder_name || '',
    };
    markBackendHealthy('后端连接正常');
    scheduleDialog.data = data;
    scheduleDialog.preview = data.preview || [];
    scheduleDialog.previewError = data.preview_error || '';
  } catch (error) {
    if (seq !== scheduleLoadSeq || scheduleDialog.task?.id !== row.id) {
      return;
    }
    scheduleDialog.error = error.message;
    await handleRequestFailure(error, { toastTitle: '调度配置加载失败' });
  } finally {
    if (seq === scheduleLoadSeq && scheduleDialog.task?.id === row.id) {
      scheduleDialog.loading = false;
    }
  }
}

async function closeScheduleDialog(options = {}) {
  if (scheduleDialog.saving) return;
  if (
    options.dirty &&
    !(await requestConfirm({
      eyebrow: '未保存的修改',
      title: '放弃未保存的配置？',
      message: '当前修改尚未保存。关闭后会恢复已保存的配置。',
      confirmText: '放弃修改',
      cancelText: '继续编辑',
    }))
  )
    return;
  if (scheduleDialog.saving) {
    return;
  }
  scheduleLoadSeq += 1;
  schedulePreviewSeq += 1;
  scheduleDialog.previewLoading = false;
  scheduleDialog.open = false;
}

async function previewSchedule(form) {
  if (!scheduleDialog.open || !scheduleDialog.task) {
    return;
  }
  const seq = ++schedulePreviewSeq;
  scheduleDialog.previewLoading = true;
  scheduleDialog.previewError = '';
  try {
    const data = await api.previewTaskSchedule(
      scheduleRequest(scheduleDialog.task.id, form),
    );
    if (seq !== schedulePreviewSeq) {
      return;
    }
    scheduleDialog.preview = data.preview || [];
  } catch (error) {
    if (seq !== schedulePreviewSeq) {
      return;
    }
    scheduleDialog.preview = [];
    scheduleDialog.previewError = error.message;
  } finally {
    if (seq === schedulePreviewSeq) {
      scheduleDialog.previewLoading = false;
    }
  }
}

async function saveSchedule(form) {
  if (!scheduleDialog.task || scheduleDialog.saving) {
    return;
  }
  const taskId = scheduleDialog.task.id;
  scheduleDialog.saving = true;
  scheduleDialog.error = '';
  try {
    const data = await api.updateTaskSchedule(scheduleRequest(taskId, form));
    if (scheduleDialog.task?.id !== taskId) {
      return;
    }
    if (data.pid && data.pid !== taskId) {
      throw new Error(`后端保存 PID ${data.pid} 与当前任务 ${taskId} 不一致。`);
    }
    markBackendHealthy('后端连接正常');
    scheduleDialog.data = data;
    scheduleDialog.preview = data.preview || [];
    scheduleDialog.previewError = data.preview_error || '';
    scheduleDialog.open = false;
    pushToast(
      data.application?.status === 'failed' ? 'error' : 'success',
      '任务配置已保存',
      data.application?.status === 'failed'
        ? `保存成功，但生效失败：${data.application.message}。请刷新任务重新应用。`
        : `${taskId} 已生效。`,
    );
    await Promise.all([loadTasks(), loadDashboard({ silent: true })]);
  } catch (error) {
    scheduleDialog.error = error.message;
    await handleRequestFailure(error, { toastTitle: '调度策略保存失败' });
  } finally {
    scheduleDialog.saving = false;
  }
}

async function openLatestLog(row) {
  const serial = ++logDetailSerial;
  showModal(`最新输出：${row.name || row.id}`, '正在读取输出…');
  try {
    const content = await api.detailLog({ id: row.id });
    if (serial !== logDetailSerial || !modal.open) return;
    markBackendHealthy('后端连接正常');
    modal.content = formatModalContent(content || '本次执行没有日志输出。');
  } catch (error) {
    if (serial !== logDetailSerial || !modal.open) return;
    modal.content = error.message;
    await handleRequestFailure(error, { toastTitle: '日志读取失败' });
  }
}

async function openTaskLog(row) {
  const serial = ++logDetailSerial;
  showModal(`任务日志：${row.id}`, '正在加载日志...');
  try {
    if (/^[a-f0-9]{32}$/.test(row.logid)) {
      try {
        await api.execution(row.logid);
        if (serial !== logDetailSerial || !modal.open) return;
        closeModal();
        openExecution(row.logid);
        return;
      } catch (error) {
        if (!['HTTP_400', 'HTTP_404'].includes(error.code)) throw error;
        // Archived and legacy history may only retain the database log.
      }
    }
    const content = await api.taskLogDetail({
      id: row.logid,
      end_time: row.datetime,
      pid: row.id,
    });
    markBackendHealthy('后端连接正常');
    if (serial !== logDetailSerial || !modal.open) return;
    modal.content = formatModalContent(content);
  } catch (error) {
    if (serial !== logDetailSerial || !modal.open) return;
    await handleRequestFailure(error, { toastTitle: '日志读取失败' });
    modal.content = error.message || ' ';
  }
}

function handleVisibilityChange() {
  syncDashboardPolling();
  if (!token.value || document.visibilityState === 'hidden') {
    return;
  }
  if (!eventSource) {
    startLiveEvents();
  }
  refreshActiveView();
}

watch(view, async (nextView) => {
  syncDashboardPolling();
  if (!token.value) {
    return;
  }
  if (nextView === 'dashboard') {
    await loadDashboard();
  }
  if (nextView === 'tasks' && !tasks.items.length) {
    await Promise.all([loadTasks(), loadGroups()]);
  }
  if (nextView === 'taskLogs' && !taskLogs.rows.length) {
    await Promise.all([loadTaskLogs(), loadTaskIds()]);
  }
  if (nextView === 'systemLogs' && !systemLogs.rows.length) {
    await Promise.all([loadSystemLogs(), loadSystemIds()]);
  }
});

function applyRoute() {
  const route = readRoute(window.location.hash);
  if (token.value && user.roles.length && !canManage.value && !['tasks', 'matrix', 'taskLogs'].includes(route.view)) {
    switchView('tasks');
    return;
  }
  view.value = route.view;
  if (!token.value) return;
  detailPid.value = route.run ? '' : route.pid;
  executionRunId.value = route.run;
  if (route.view === 'taskLogs') {
    const mapping = {
      taskid: 'taskid',
      taskname: 'taskname',
      state: 'taskstate',
      start: 'startDate',
      end: 'endDate',
      scope: 'scope',
    };
    for (const [query, key] of Object.entries(mapping))
      if (route.params.has(query))
        taskLogs.params[key] = route.params.get(query).slice(0, 200);
    if (!['online', 'archive', 'all'].includes(taskLogs.params.scope))
      taskLogs.params.scope = 'online';
    loadTaskLogs(true);
  }
}
function syncRoute() {
  const current = readRoute(window.location.hash);
  const values = Object.fromEntries(current.params);
  values.pid = detailPid.value;
  values.run = executionRunId.value;
  if (view.value === 'taskLogs')
    Object.assign(values, {
      taskid: taskLogs.params.taskid,
      taskname: taskLogs.params.taskname,
      state: taskLogs.params.taskstate,
      start: taskLogs.params.startDate,
      end: taskLogs.params.endDate,
      scope: taskLogs.params.scope,
    });
  const hash = routeHash(view.value, values);
  if (hash !== window.location.hash) window.history.pushState(null, '', hash);
}
window.addEventListener('hashchange', applyRoute);
watch([detailPid, executionRunId], syncRoute);

function openExecution(runId) {
  detailPid.value = '';
  executionRunId.value = runId;
}
async function openActiveExecution(row) {
  try {
    const runs = await api.runs(row.id);
    const active = runs.find((run) =>
      ['running', 'queued'].includes(run.status),
    );
    if (active) openExecution(active.run_id);
    else detailPid.value = row.id;
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '执行记录读取失败' });
  }
}
function openMatrixLogs(record) {
  taskLogs.params.taskid = record.pid;
  taskLogs.params.taskname = '';
  taskLogs.params.scope = 'online';
  taskLogs.params.startDate = record.start_time.slice(0, 10);
  taskLogs.params.endDate = record.end_time.slice(0, 10);
  taskLogs.params.taskstate = '';
  matrixLogRange.value = [record.query_start, record.query_end];
  switchView('taskLogs');
  loadTaskLogs(true);
}
async function retryExecution(record) {
  if (retryingExecution.value) return;
  const confirmed = await requestConfirm({
    title: '再次执行任务',
    message: `手动执行 ${record.pid}，会生成新的执行记录。`,
    details: [
      '请先确认上次执行是否已写入业务数据；系统不会自动重试或补跑重启前的执行。',
    ],
    confirmText: '再执行一次',
    danger: true,
  });
  if (!confirmed) return;
  retryingExecution.value = true;
  try {
    const result = await api.callTask({ pid: record.pid });
    openExecution(result.run_id);
    await loadTasks();
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '再次执行失败' });
  } finally {
    retryingExecution.value = false;
  }
}
function showFilteredTasks(status) {
  tasks.params.status = status;
  switchView('tasks');
  loadTasks(true);
}
async function confirmRestore(payload) {
  const confirmed = await requestConfirm({
    title: '恢复调度配置',
    message: `将 ${payload.pid} 恢复为历史版本 ${payload.restore_version}，并生成新版本。`,
    details: ['会沿用所选版本的调度启用状态；正在执行的实例继续运行。'],
    confirmText: '恢复配置',
    danger: true,
  });
  if (!confirmed) return;
  try {
    const result = await api.restore({
      pid: payload.pid,
      version: payload.version,
      restore_version: payload.restore_version,
    });
    pushToast(
      result.application?.status === 'failed' ? 'error' : 'success',
      '配置已恢复',
      result.application?.message || '已生成新版本并应用调度。',
    );
    payload.done();
    loadTasks();
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '恢复配置失败' });
  }
}

onMounted(async () => {
  document.addEventListener('visibilitychange', handleVisibilityChange);
  if (!navItems.some((item) => item.id === view.value)) {
    view.value = 'dashboard';
  }

  const reachable = await checkBackend({ silent: true });
  ready.value = true;

  if (!reachable) {
    return;
  }
  const hadToken = Boolean(token.value);
  try {
    await loadUser();
    await Promise.all([...(canManage.value ? [loadDashboard()] : []), loadTasks(), loadGroups()]);
    startLiveEvents();
    syncDashboardPolling();
    applyRoute();
  } catch (error) {
    if (isAuthError(error)) {
      clearToken();
      token.value = '';
    }
    if (hadToken || !isAuthError(error))
      pushToast('error', '登录状态检查失败', error.message);
  }
});

onUnmounted(() => {
  window.removeEventListener('hashchange', applyRoute);
  stopLiveEvents();
  document.removeEventListener('visibilitychange', handleVisibilityChange);
});
</script>
