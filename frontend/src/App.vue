<template>
  <CursorLight />
  <div v-if="assetFailure" class="asset-recovery" role="alert">
    <strong>页面资源加载失败，可能已发布新版本</strong>
    <p>请刷新以获取当前版本。若有未保存的修改，请先保存或复制；刷新前也会提醒确认。</p>
    <button class="btn primary" type="button" @click="refreshPageAssets">刷新页面资源</button>
  </div>
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
        aria-label="菜单"
        :aria-expanded="mobileNavOpen"
        aria-controls="workspace-navigation"
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
          :class="{ active: activeNav.id === item.id }"
          type="button"
          :title="item.label"
          :aria-label="item.label"
          :aria-current="activeNav.id === item.id ? 'page' : undefined"
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
        <ServiceStatus :status="backendStatus" />
        <UserMenu
          placement="sidebar"
          :name="user.name || 'Admin'"
          :avatar="user.avatar"
          :admin="canManage"
          :current="view"
          @navigate="switchView"
          @logout="handleLogout"
        />
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="page-title">
          <strong>{{ activeNav.label }}</strong>
          <span>{{ canManage ? activeNav.description : user.roles.includes('maintainer') ? '任务维护工作区 · 按授权操作' : '用户工作区 · 只读查看任务' }}</span>
        </div>
        <div class="top-actions">
          <button v-if="canManage" class="btn" type="button" @click="switchView('gitlab')">代码更新<span v-if="gitlabSummary?.unread && gitlabSummary.count"> · {{ gitlabSummary.count }}</span></button>
          <button v-if="canManage && (!backendStatus.reachable || Object.values(backendStatus.components || {}).some(item => item.status === 'unavailable'))" class="btn warning" @click="switchView('systemLogs')">查看平台事件</button>

        </div>
      </header>

      <section
        class="content"
        :class="{ 'dashboard-content': view === 'dashboard' }"
      >
        <div v-if="showGitlabReminder && view !== 'gitlab'" class="inline-alert content-alert gitlab-reminder" role="status">
          <strong>GitLab 有新的代码更新</strong>
          <span>待合并 {{ gitlabSummary.pending_merge }} 项，待部署 / 发布 {{ gitlabSummary.pending_release }} 项。</span>
          <button class="btn primary" @click="switchView('gitlab')">查看代码差异</button>
          <button class="btn" @click="dismissGitlabReminder">稍后处理</button>
        </div>
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

        <MaintenanceControl v-if="canManage && view === 'admin'" :confirm="requestConfirm" />
        <template v-if="view === 'dashboard'">
          <DashboardView
            :dashboard="dashboard"
            :can-manage="canManage"
            @detail="detailPid = $event"
            @execution="openExecution"
            @admin="switchView('admin')"
            @queue="switchView('queue')"
            @tasks="showFilteredTasks"
          />
        </template>

        <template v-else-if="['matrix','taskLogs','queue'].includes(view)">
          <ExecutionMatrixWorkspace
            :user-key="user.name"
            :can-manage="canManage"
            :confirm="requestConfirm"
            :selected-tab="view==='taskLogs'?'logs':view==='queue'?'queue':matrixTab"
            @select="selectExecutionTab"
            @record="openMatrixRecord"
            @history="openTaskHistory"
            @settings="switchView('admin')"
            @task="detailPid = $event"
            @execution="openExecution"
            @logs="openMatrixLogs"
          >
            <template #logs>
              <ExecutionLogsView
                :task-logs="taskLogs" :matrix-log-range="matrixLogRange"
                @range="setLogRange" @search="searchTaskLogs" @reset="resetTaskLogFilters"
                @open="openTaskLog" @page="setTaskLogPage" @page-size="setTaskLogPageSize"
                @updates="loadTaskLogs(true)" @tasks="switchView('tasks')"
                @clear-filter="clearTaskLogFilter"
              />
            </template>
          </ExecutionMatrixWorkspace>
        </template>

        <template v-else-if="view === 'tasks'">
          <TaskWorkspaceView
            :tasks="tasks" :user-key="user.name"
            :selected-tasks="selectedTasks"
            :favorites="favorites"
            :only-favorites="onlyFavorites"
            :batch-busy="batchBusy"
            :busy="busy"
            :pending-actions="pendingActions"
            :can-manage="canManage"
            :can-operate="canOperate"
            :can-publish="canManage || user.taskAccess.capabilities.includes('publish')"
            @release="openPackages"
            @gitlab="switchView('gitlab')"
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
          >
            <template #maintenance><MaintenanceControl v-if="canManage" :confirm="requestConfirm" compact /></template>
          </TaskWorkspaceView>
        </template>

        <template v-else-if="view === 'packages' && canManage"
          ><TaskExamples /></template>
        <template v-else-if="view === 'gitlab' && canManage"><GitlabUpdates @state="acceptGitlabState" /></template>
        <template v-else-if="['admin','connections','repository'].includes(view) && canManage"
          ><AdminPanel :confirm="requestConfirm"
        /></template>
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
  <TaskReleaseDialog v-if="packagePid && (canManage || user.roles.includes('maintainer'))" :pid="packagePid" :allow-operations="canManage" :confirm="requestConfirm" @execution="openExecution" @close="packagePid = ''" @changed="refreshPackageTasks" />
  <TaskDetailDialog
    :pid="detailPid"
    :confirm="requestConfirm"
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
import { assetFailure, isAssetFailure } from './assetRecovery';
import { useBackendStatus } from './composables/useBackendStatus';
import { useLiveUpdates } from './composables/useLiveUpdates';

import {
  defineAsyncComponent,
  nextTick,
  onErrorCaptured,
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
import { useGitlabUpdates } from './composables/useGitlabUpdates';
import UserMenu from './components/UserMenu.vue';
import { api, clearToken, getToken, setToken } from './api';
import { navItems } from './workspaceNavigation.js';
import { useScheduleWorkspace } from './composables/useScheduleWorkspace.js';
import { useTaskActions } from './composables/useTaskActions.js';
import ConfirmDialog from './components/ConfirmDialog.vue';
import ScheduleDialog from './components/ScheduleDialog.vue';
import { useTaskWorkspace } from './composables/useTaskWorkspace';
import { recentLogDates, useLogWorkspace } from './composables/useLogWorkspace';
import { useDashboardWorkspace } from './composables/useDashboardWorkspace';
import MaintenanceControl from './components/MaintenanceControl.vue';
import TaskDetailDialog from './components/TaskDetailDialog.vue';
import ExecutionDialog from './components/ExecutionDialog.vue';
const AdminPanel = defineAsyncComponent(
  () => import('./components/AdminPanel.vue'),
);
const GitlabUpdates = defineAsyncComponent(() => import('./components/GitlabUpdates.vue'));
const TaskExamples = defineAsyncComponent(() => import('./components/TaskExamples.vue'));
const TaskReleaseDialog = defineAsyncComponent(() => import('./components/TaskReleaseDialog.vue'));
const ExecutionMatrixWorkspace = defineAsyncComponent(
  () => import('./components/ExecutionMatrixWorkspace.vue'),
);
import { confirmUnsaved } from './composables/useUnsavedChanges';
import { useConfirm } from './composables/useConfirm';
onErrorCaptured(error => { if (isAssetFailure(error)) { assetFailure.value = true; return false; } });
async function refreshPageAssets() {
  if (!await confirmUnsaved(requestConfirm)) return;
  const target = new URL(window.location.href);
  target.searchParams.set('_wfs_reload', String(Date.now()));
  window.location.replace(target.href);
}

const loginVisual = shallowRef(null);
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

const ready = ref(false);
const token = ref(getToken());
const view = ref(readRoute(window.location.hash).view);
const matrixTab = ref(readRoute(window.location.hash).params.get('tab') || 'recent');
const packagePid = ref('');
const mobileNavOpen = ref(false);
const loginLoading = ref(false);
const busy = ref(false);
const detailPid = ref('');
const executionRunId = ref('');
const toasts = ref([]);
const { confirmState, requestConfirm, resolveConfirm } = useConfirm();


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
  taskAccess:{capabilities:[]},
});
const canManage = computed(() => user.roles.includes('admin'));
const gitlabEnabled = computed(() => Boolean(token.value) && canManage.value);
const { summary: gitlabSummary, showReminder: showGitlabReminder, accept: acceptGitlabState, dismiss: dismissGitlabReminder } = useGitlabUpdates(gitlabEnabled);
const canOperate = computed(() => canManage.value || user.roles.includes('maintainer'));
const visibleNavItems = computed(() =>
  navItems.filter(
    (item) => canManage.value ? ['dashboard','tasks','matrix','gitlab'].includes(item.id) : ['tasks', 'matrix'].includes(item.id),
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
  hasCurrentTaskLogQuery,
  clearTaskLogFilter,
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

const {scheduleDialog,openScheduleDialog,closeScheduleDialog,previewSchedule,saveSchedule}=useScheduleWorkspace({markBackendHealthy,handleRequestFailure,requestConfirm,pushToast,loadTasks,loadDashboard});
const {pendingActions,retryingExecution,canCallTask,callTaskTitle,editTask,handleCallTask,pauseTask,retryExecution,confirmRestore}=useTaskActions({view,taskLogs,loadTasks,loadTaskLogs,markBackendHealthy,handleRequestFailure,requestConfirm,pushToast,openExecution});

const activeNav = computed(
  () => navItems.find((item) => item.id === (['queue','taskLogs'].includes(view.value)?'matrix':['connections','repository'].includes(view.value)?'admin':view.value)) || navItems[0],
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

async function loadUser() {
  const data = await api.userInfo();
  markBackendHealthy('后端连接正常');
  user.project = data.project || '定时任务调度';
  user.name = data.name || 'Admin';
  user.avatar = data.avatar || '/static/img/head.gif';
  user.roles = data.roles || [];
  user.taskAccess=data.task_access || {capabilities:[]};

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
  if(!await confirmUnsaved(requestConfirm))return;

  try {
    await api.logout();
  } catch (error) {
    await handleRequestFailure(error);
  }
  clearToken();
  token.value = '';
  user.roles = [];
    packagePid.value = '';
  detailPid.value = '';
  executionRunId.value = '';
  scheduleDialog.open = false;
  scheduleDialog.data = null;
  closeModal();
  stopLiveEvents();
}

async function switchView(nextView) {
  const queueTab=nextView==='queue';
  if(queueTab)nextView='matrix';
  if(nextView!==view.value && !await confirmUnsaved(requestConfirm))return;
  if (token.value && !canManage.value && !['tasks', 'matrix', 'taskLogs'].includes(nextView)) nextView = 'tasks';
  view.value = nextView;
  window.location.hash = queueTab ? 'matrix?tab=queue' : routeHash(nextView);
  mobileNavOpen.value = false;
  syncDashboardPolling();
}

function openPackages(pid) {
  detailPid.value = '';
  if (pid) packagePid.value = pid;
  else switchView('packages');
}
async function refreshPackageTasks() {
  await Promise.all([loadTasks(), loadGroups()]);
}

async function refreshActiveView(options = {}) {
  const silent=options.silent===true;
  const reachable = await checkBackend({ silent: true });
  if (!reachable) {
    if(!silent)pushToast('error', '刷新失败', backendStatus.error);
    return;
  }

  if (view.value === 'dashboard') {
    await loadDashboard({silent});
  } else if (view.value === 'tasks') {
    await Promise.all([loadTasks(false,{silent}), ...(silent?[]:[loadGroups()])]);
  } else if (view.value === 'taskLogs') {
    await Promise.all([loadTaskLogs(false,{silent,buffer:silent}), ...(silent?[]:[loadTaskIds()])]);
  } else if (['matrix','queue'].includes(view.value)) {
    window.dispatchEvent(new CustomEvent('wfs:matrix-refresh',{detail:{silent}}));
  } else if (view.value === 'packages') {
    window.dispatchEvent(new Event('wfs:packages-refresh'));
  } else if(view.value==='systemLogs') {
    await Promise.all([loadSystemLogs(), loadSystemIds()]);
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
  const origin = document.activeElement;
  const serial = ++logDetailSerial;
  showModal(`任务日志：${row.id}`, '正在加载日志...');
  try {
    if (/^[a-f0-9]{32}$/.test(row.logid)) {
      try {
        await api.execution(row.logid);
        if (serial !== logDetailSerial || !modal.open) return;
        closeModal();
        await nextTick();
        origin?.focus({ preventScroll: true });
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
  startLiveEvents();
  refreshActiveView({silent:true});
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
  if (nextView === 'systemLogs' && !systemLogs.rows.length) {
    await Promise.all([loadSystemLogs(), loadSystemIds()]);
  }
});

async function applyRoute() {
  const route = readRoute(window.location.hash);
  if (token.value && user.roles.length && !canManage.value && !['tasks', 'matrix', 'taskLogs'].includes(route.view)) {
    switchView('tasks');
    return;
  }
  if((route.view!==view.value || route.pid!==detailPid.value) && !await confirmUnsaved(requestConfirm)){window.history.replaceState(null,'',routeHash(view.value,{pid:detailPid.value,run:executionRunId.value}));return;}
  view.value = route.view;
  matrixTab.value = route.params.get('tab') || 'recent';
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
    const dates=recentLogDates();
    const defaults={start:dates.start,end:dates.end,scope:'online'};
    for (const [query, key] of Object.entries(mapping))
      taskLogs.params[key] = (route.params.get(query) ?? defaults[query] ?? '').slice(0, 200);
    const range=[route.params.get('from'),route.params.get('to')];
    matrixLogRange.value=range.every(value=>value && value.length<=32 && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d{1,6})?$/.test(value))?range:[];
    if (!['online', 'archive', 'all'].includes(taskLogs.params.scope))
      taskLogs.params.scope = 'online';
    if (!hasCurrentTaskLogQuery()) loadTaskLogs(true);
    if (!taskLogs.ids.length) loadTaskIds();
  }
}
function syncRoute() {
  const current = readRoute(window.location.hash);
  const values = Object.fromEntries(current.params);
  if(!detailPid.value || current.pid!==detailPid.value){delete values.detail;delete values.detailRun;}
  values.pid = detailPid.value;
  values.run = executionRunId.value;
  if (view.value === 'taskLogs') Object.assign(values, logRouteValues());
  const hash = routeHash(view.value, values);
  if (hash !== window.location.hash) window.history.pushState(null, '', hash);
}
function logRouteValues() {
  return {
      taskid: taskLogs.params.taskid,
      taskname: taskLogs.params.taskname,
      state: taskLogs.params.taskstate,
      start: taskLogs.params.startDate,
      end: taskLogs.params.endDate,
      scope: taskLogs.params.scope,
      from: matrixLogRange.value[0] || '',
      to: matrixLogRange.value[1] || '',
  };
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
function selectExecutionTab(tab) {
  const hash=tab==='logs'?routeHash('taskLogs',logRouteValues()):routeHash('matrix',{tab});
  if(hash!==window.location.hash)window.location.hash=hash;
}
function openMatrixRecord(record) {
  return openTaskLog({id:record.pid,logid:record.run_id,datetime:record.query_end || record.end_time});
}
function openTaskHistory(record) {
  const dates=recentLogDates();
  const end=record.end_time?.slice(0,10) || dates.end;
  window.location.hash=routeHash('taskLogs',{taskid:record.pid,scope:'all',start:end<dates.start?end:dates.start,end:end<dates.start?end:dates.end});
}
function openMatrixLogs(record) {
  window.location.hash=routeHash('taskLogs',{taskid:record.pid,taskname:'',state:'',scope:record.scope || 'online',start:record.start_time.slice(0,10),end:record.end_time.slice(0,10),from:record.query_start,to:record.query_end});
}
function showFilteredTasks(status) {
  tasks.params.status = status;
  switchView('tasks');
  loadTasks(true);
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

<style scoped>
.asset-recovery{position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:1200;width:min(560px,calc(100vw - 32px));box-sizing:border-box;padding:20px;border:1px solid var(--warning,#d4af65);border-radius:12px;background:var(--panel,#171717);color:var(--ink,#fff);box-shadow:0 12px 40px #0008;display:grid;gap:12px}.asset-recovery p{margin:0;line-height:1.6}.asset-recovery .btn{justify-self:start}
</style>
