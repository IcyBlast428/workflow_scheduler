<template>
  <div v-if="!ready" class="boot-screen">
    <div class="boot-card">
      <div class="boot-mark">WFS</div>
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

  <main v-else-if="!token" class="login-screen">
    <section class="login-panel">
      <div class="login-brief">
        <div class="brand-mark">WFS</div>
        <h1>定时任务调度</h1>
        <p>面向内网运维任务的调度控制台，集中管理任务扫描、暂停启动、运行日志与系统异常记录。</p>
      </div>
      <form class="login-form" @submit.prevent="handleLogin">
        <div class="login-form-head">
          <div>
            <h2>登录控制台</h2>
            <p class="hint">使用后端配置中的管理员账户登录。</p>
          </div>
        </div>
        <div
          v-if="backendStatus.error"
          class="inline-alert danger"
        >
          <strong>后端未连接</strong>
          <span>{{ backendStatus.error }}</span>
          <button class="btn" type="button" @click="checkBackend()">重试</button>
        </div>
        <div v-else class="inline-alert success">
          <strong>后端已连接</strong>
          <span>{{ backendStatus.message }}</span>
        </div>
        <div class="form-row">
          <label for="username">用户名</label>
          <input id="username" v-model.trim="loginForm.username" class="input" autocomplete="username">
        </div>
        <div class="form-row">
          <label for="password">密码</label>
          <input id="password" v-model="loginForm.password" class="input" type="password" autocomplete="current-password">
        </div>
        <button class="btn primary" type="submit" :disabled="loginLoading || !backendStatus.reachable">
          <span class="btn-icon">></span>
          {{ loginLoading ? '登录中...' : '登录' }}
        </button>
      </form>
    </section>
  </main>

  <div v-else class="app-shell">
    <aside class="sidebar" :class="{ open: mobileNavOpen }">
      <div class="brand">
        <div class="brand-mark">WFS</div>
        <div class="brand-copy">
          <h1>{{ user.project || '定时任务调度' }}</h1>
          <span>Workflow Scheduler</span>
        </div>
      </div>
      <button class="btn icon-only mobile-menu" type="button" title="菜单" @click="mobileNavOpen = !mobileNavOpen">≡</button>
      <nav class="nav">
        <button
          v-for="item in navItems"
          :key="item.id"
          class="nav-button"
          :class="{ active: view === item.id }"
          type="button"
          :title="item.label"
          :aria-label="item.label"
          @click="switchView(item.id)"
        >
          <span class="nav-icon" aria-hidden="true">
            <svg class="nav-svg" viewBox="0 0 24 24" role="img">
              <path
                v-for="path in item.iconPaths"
                :key="path"
                :d="path"
              />
            </svg>
          </span>
          <span class="nav-label">{{ item.label }}</span>
        </button>
      </nav>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="page-title">
          <strong>{{ activeNav.label }}</strong>
          <span>{{ activeNav.description }}</span>
        </div>
        <div class="top-actions">
          <button class="btn" type="button" @click="toggleTheme">
            <span class="btn-icon">{{ theme === 'dark' ? '☾' : '☼' }}</span>
            {{ theme === 'dark' ? '深色' : '浅色' }}
          </button>
          <button class="btn warning" type="button" :disabled="busy" @click="handleUpdateCode">
            <span class="btn-icon">^</span>
            更新代码
          </button>
          <div class="status-chip" :class="backendStatus.reachable ? 'online' : 'offline'">
            <strong>{{ backendStatus.reachable ? '后端正常' : '后端异常' }}</strong>
            <span>{{ backendStatus.checkedAt || '未检测' }}</span>
          </div>
          <div class="status-chip" :class="liveState.connected ? 'online' : 'offline'">
            <strong>{{ liveState.connected ? '实时同步' : '实时断开' }}</strong>
            <span>{{ liveState.lastEvent || '等待连接' }}</span>
          </div>
          <div class="user-chip">
            <img class="avatar" :src="user.avatar || '/static/img/head.gif'" alt="">
            <span>{{ user.name || 'Admin' }}</span>
          </div>
          <button class="btn ghost" type="button" @click="handleLogout">退出</button>
        </div>
      </header>

      <section class="content" :class="{ 'dashboard-content': view === 'dashboard' }">
        <div v-if="backendStatus.error" class="inline-alert danger content-alert">
          <strong>当前后端连接异常</strong>
          <span>{{ backendStatus.error }}</span>
          <button class="btn" type="button" @click="refreshActiveView()">重新检测</button>
        </div>

        <template v-if="view === 'dashboard'">
          <div v-if="dashboard.loading" class="loading-bar"></div>
          <div v-if="dashboard.error" class="error-state">{{ dashboard.error }}</div>
          <template v-else>
            <section class="panel cpu-panel">
              <div class="panel-head cpu-panel-head">
                <div>
                  <h2>机器 CPU / 内存与任务运行段</h2>
                  <p>最近 {{ dashboard.cpu_timeline.retention_hours || 6 }} 小时采样，任务运行段叠加在资源曲线上。</p>
                </div>
                <div class="cpu-head-actions">
                  <span class="tag info">CPU {{ cpuCurrentText }}</span>
                  <span class="tag warning">内存 {{ memoryCurrentText }}</span>
                  <span v-if="dashboard.cpu_timeline.warning" class="tag warning">采样异常</span>
                </div>
              </div>
              <CpuTimelineChart
                :samples="dashboard.cpu_timeline.samples"
                :markers="dashboard.cpu_timeline.markers"
                :retention-hours="dashboard.cpu_timeline.retention_hours || 6"
              />
            </section>
          </template>
        </template>

        <template v-else-if="view === 'tasks'">
          <div class="summary-grid">
            <div class="metric-card">
              <span>任务总数</span>
              <strong>{{ tasks.total }}</strong>
            </div>
            <div class="metric-card">
              <span>本页运行中</span>
              <strong>{{ taskSummary.running }}</strong>
            </div>
            <div class="metric-card">
              <span>本页执行中</span>
              <strong>{{ taskSummary.pending }}</strong>
            </div>
            <div class="metric-card">
              <span>本页配置异常</span>
              <strong>{{ taskSummary.invalid }}</strong>
            </div>
            <div class="metric-card">
              <span>本页累计失败</span>
              <strong>{{ taskSummary.failed }}</strong>
            </div>
          </div>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h2>任务列表</h2>
                <p>从 app/jobs 目录扫描任务代码，运行配置和调度策略由前端维护。</p>
              </div>
              <div class="filter-actions">
                <button class="btn" type="button" :disabled="tasks.loading" @click="reloadTasks(false)">
                  <span class="btn-icon">+</span>
                  同步任务
                </button>
                <button class="btn danger" type="button" :disabled="tasks.loading" @click="reloadTasks(true)">
                  <span class="btn-icon">!</span>
                  全量重载
                </button>
              </div>
            </div>
            <form class="filter-grid" @submit.prevent="loadTasks(true)">
              <div class="form-row">
                <label for="taskid">任务 ID</label>
                <input id="taskid" v-model.trim="tasks.params.taskid" class="input" placeholder="PID">
              </div>
              <div class="form-row">
                <label for="taskname">任务名称</label>
                <input id="taskname" v-model.trim="tasks.params.taskname" class="input" placeholder="名称关键字">
              </div>
              <div class="form-row">
                <label for="taskgroup">任务分组</label>
                <select id="taskgroup" v-model="tasks.params.taskgroup" class="select">
                  <option value="">全部分组</option>
                  <option v-for="group in tasks.groups" :key="group" :value="group">{{ group }}</option>
                </select>
              </div>
              <div class="filter-actions">
                <button class="btn primary" type="submit">
                  <span class="btn-icon">?</span>
                  搜索
                </button>
                <button class="btn" type="button" @click="resetTaskFilters">清空</button>
              </div>
            </form>
            <div v-if="tasks.loading" class="loading-bar"></div>
            <div v-if="tasks.error" class="error-state">{{ tasks.error }}</div>
            <div v-else-if="!tasks.items.length && !tasks.loading" class="empty-state">
              <strong>没有匹配的任务</strong>
              <span>可以清空筛选条件，或点击“同步任务”同步 app/jobs 目录。</span>
            </div>
            <TaskTable
              v-else
              :rows="tasks.items"
              :busy="busy"
              @action="editTask"
              @pause="pauseTask"
              @call="handleCallTask"
              @schedule="openScheduleDialog"
              @log="openLatestLog"
            />
            <Pagination
              :page="tasks.params.currentPage"
              :page-size="tasks.params.pagesize"
              :total="tasks.total"
              @page="setTaskPage"
              @page-size="setTaskPageSize"
            />
          </section>
        </template>

        <template v-else-if="view === 'taskLogs'">
          <section class="panel">
            <div class="panel-head">
              <div>
                <h2>调度日志</h2>
                <p>查看任务脚本每次执行的开始时间、结束时间、耗时与输出摘要。</p>
              </div>
            </div>
            <form class="filter-grid logs" @submit.prevent="loadTaskLogs(true)">
              <div class="form-row">
                <label for="task-log-id">任务 ID</label>
                <input id="task-log-id" v-model.trim="taskLogs.params.taskid" class="input" list="task-id-options" placeholder="PID">
                <datalist id="task-id-options">
                  <option v-for="item in taskLogs.ids" :key="item.id" :value="item.id"></option>
                </datalist>
              </div>
              <div class="form-row">
                <label for="task-log-state">执行状态</label>
                <select id="task-log-state" v-model="taskLogs.params.taskstate" class="select">
                  <option value="">全部状态</option>
                  <option value="成功">成功</option>
                  <option value="失败">失败</option>
                </select>
              </div>
              <div class="form-row">
                <label for="task-log-start">开始日期</label>
                <input id="task-log-start" v-model="taskLogs.params.startDate" class="input" type="date">
              </div>
              <div class="form-row">
                <label for="task-log-end">结束日期</label>
                <input id="task-log-end" v-model="taskLogs.params.endDate" class="input" type="date">
              </div>
              <div class="filter-actions">
                <button class="btn primary" type="submit">
                  <span class="btn-icon">?</span>
                  搜索
                </button>
                <button class="btn" type="button" @click="resetTaskLogFilters">清空</button>
              </div>
            </form>
            <div v-if="taskLogs.loading" class="loading-bar"></div>
            <LogTable
              kind="task"
              :rows="taskLogs.rows"
              :loading="taskLogs.loading"
              :error="taskLogs.error"
              @open="openTaskLog"
            />
            <Pagination
              :page="taskLogs.params.currentPage"
              :page-size="taskLogs.params.pagesize"
              :total="taskLogs.total"
              @page="setTaskLogPage"
              @page-size="setTaskLogPageSize"
            />
          </section>
        </template>

        <template v-else>
          <section class="panel">
            <div class="panel-head">
              <div>
                <h2>系统日志</h2>
                <p>查看调度器事件、任务异常和系统级报错记录。</p>
              </div>
            </div>
            <form class="filter-grid logs" @submit.prevent="loadSystemLogs(true)">
              <div class="form-row">
                <label for="system-log-id">任务 ID</label>
                <input id="system-log-id" v-model.trim="systemLogs.params.systemids" class="input" list="system-id-options" placeholder="PID">
                <datalist id="system-id-options">
                  <option v-for="item in systemLogs.ids" :key="item.id" :value="item.id"></option>
                </datalist>
              </div>
              <div class="form-row">
                <label for="system-log-start">开始日期</label>
                <input id="system-log-start" v-model="systemLogs.params.startDate" class="input" type="date">
              </div>
              <div class="form-row">
                <label for="system-log-end">结束日期</label>
                <input id="system-log-end" v-model="systemLogs.params.endDate" class="input" type="date">
              </div>
              <div class="filter-actions">
                <button class="btn primary" type="submit">
                  <span class="btn-icon">?</span>
                  搜索
                </button>
                <button class="btn" type="button" @click="resetSystemLogFilters">清空</button>
              </div>
            </form>
            <div v-if="systemLogs.loading" class="loading-bar"></div>
            <LogTable
              kind="system"
              :rows="systemLogs.rows"
              :loading="systemLogs.loading"
              :error="systemLogs.error"
              @open="(row) => showModal(`系统日志：${row.id}`, row.systeminfo || ' ')"
            />
            <Pagination
              :page="systemLogs.params.currentPage"
              :page-size="systemLogs.params.pagesize"
              :total="systemLogs.total"
              @page="setSystemLogPage"
              @page-size="setSystemLogPageSize"
            />
          </section>
        </template>
      </section>
    </div>
  </div>

  <div v-if="modal.open" class="modal-backdrop" @click.self="closeModal">
    <section class="modal">
      <header class="modal-head">
        <h3>{{ modal.title }}</h3>
        <div class="modal-actions">
          <button class="btn" type="button" @click="toggleWrap">
            {{ modal.wrap ? '单行滚动' : '自动换行' }}
          </button>
          <button class="btn" type="button" @click="copyModalContent">复制内容</button>
          <button class="btn icon-only" type="button" title="关闭" @click="closeModal">×</button>
        </div>
      </header>
      <div class="modal-body">
        <pre class="log-pre" :class="{ nowrap: !modal.wrap }">{{ modal.content }}</pre>
      </div>
    </section>
  </div>

  <div class="toast-root" aria-live="polite">
    <div v-for="toast in toasts" :key="toast.id" class="toast" :class="toast.type">
      <strong>{{ toast.title }}</strong>
      <span>{{ toast.message }}</span>
    </div>
  </div>

  <ConfirmDialog :model-value="confirmState" @resolve="resolveConfirm" />
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
    @preview="previewSchedule"
  />
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { api, clearToken, getToken, setToken } from './api';
import ConfirmDialog from './components/ConfirmDialog.vue';
import CpuTimelineChart from './components/CpuTimelineChart.vue';
import LogTable from './components/LogTable.vue';
import Pagination from './components/Pagination.vue';
import ScheduleDialog from './components/ScheduleDialog.vue';
import TaskTable from './components/TaskTable.vue';
import { useConfirm } from './composables/useConfirm';

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
    description: '任务扫描、调度状态与运行控制。',
  },
  {
    id: 'taskLogs',
    label: '调度日志',
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
    label: '系统日志',
    iconPaths: [
      'M12 3.8l7 4v8.4l-7 4-7-4V7.8z',
      'M12 8v5',
      'M12 16.3v.2',
    ],
    description: '调度器事件与系统异常记录。',
  },
];

const ready = ref(false);
const token = ref(getToken());
const view = ref(window.location.hash.replace('#', '') || 'dashboard');
const theme = ref(localStorage.getItem('workflow_scheduler_theme') || 'dark');
const mobileNavOpen = ref(false);
const loginLoading = ref(false);
const busy = ref(false);
const toasts = ref([]);
const { confirmState, requestConfirm, resolveConfirm } = useConfirm();
let eventSource = null;
let dashboardPollTimer = null;
let dashboardPollInFlight = false;
let liveRefreshInFlight = false;
let scheduleLoadSeq = 0;
let schedulePreviewSeq = 0;
let liveReconnectTimer = null;
let liveTaskSignature = '';
let liveLogSignature = '';
const DASHBOARD_POLL_MS = 5000;
const LIVE_RECONNECT_MS = 3000;

const backendStatus = reactive({
  checking: false,
  reachable: false,
  error: '',
  message: '正在连接后端...',
  checkedAt: '',
});

const loginForm = reactive({
  username: 'admin',
  password: '',
});

const user = reactive({
  project: '',
  name: '',
  avatar: '',
});

const tasks = reactive({
  loading: false,
  error: '',
  items: [],
  total: 0,
  groups: [],
  params: {
    currentPage: 1,
    pagesize: 10,
    taskid: '',
    taskname: '',
    taskgroup: '',
  },
});

const liveState = reactive({
  connected: false,
  lastEvent: '',
});

const dashboard = reactive({
  loading: false,
  error: '',
  summary: {
    total: 0,
    running: 0,
    pending: 0,
    paused: 0,
    stopped: 0,
    invalid: 0,
    failed_jobs: 0,
  },
  scheduler: {
    enabled: false,
    control_url: '',
    job_count: 0,
  },
  trend: [],
  failure_rank: [],
  recent_runs: [],
  cpu_timeline: {
    samples: [],
    markers: [],
    current: null,
    current_memory: null,
    sample_interval_seconds: 5,
    retention_hours: 6,
    warning: '',
  },
  warning: '',
});

const taskLogs = reactive({
  loading: false,
  error: '',
  rows: [],
  total: 0,
  ids: [],
  params: {
    taskid: '',
    taskstate: '',
    startDate: '',
    endDate: '',
    currentPage: 1,
    pagesize: 10,
  },
});

const systemLogs = reactive({
  loading: false,
  error: '',
  rows: [],
  total: 0,
  ids: [],
  params: {
    systemids: '',
    startDate: '',
    endDate: '',
    currentPage: 1,
    pagesize: 10,
  },
});

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

const activeNav = computed(() => navItems.find((item) => item.id === view.value) || navItems[0]);

const taskSummary = computed(() => ({
  running: tasks.items.filter((item) => item.state === 'true').length,
  pending: tasks.items.filter((item) => item.pending).length,
  invalid: tasks.items.filter((item) => item.state === 'invalid').length,
  failed: tasks.items.reduce((total, item) => total + Number(item.failed_times || 0), 0),
}));

const maxTrendValue = computed(() => Math.max(
  1,
  ...dashboard.trend.map((point) => Number(point.success || 0) + Number(point.failed || 0)),
));

const cpuCurrentText = computed(() => {
  const value = Number(dashboard.cpu_timeline.current);
  return Number.isFinite(value) ? `${value.toFixed(1)}%` : '--';
});

const memoryCurrentText = computed(() => {
  const value = Number(dashboard.cpu_timeline.current_memory);
  return Number.isFinite(value) ? `${value.toFixed(1)}%` : '--';
});

function applyTheme() {
  document.documentElement.dataset.theme = theme.value;
  document.documentElement.style.colorScheme = theme.value;
  localStorage.setItem('workflow_scheduler_theme', theme.value);
}

applyTheme();

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark';
  applyTheme();
}

function trendHeight(value) {
  const height = Math.round((Number(value || 0) / maxTrendValue.value) * 96);
  return `${Math.max(4, height)}px`;
}

function pushToast(type, title, message) {
  const id = Date.now() + Math.random();
  toasts.value.push({ id, type, title, message: String(message || '') });
  window.setTimeout(() => {
    toasts.value = toasts.value.filter((toast) => toast.id !== id);
  }, 4200);
}

function markBackendHealthy(message = '后端连接正常') {
  backendStatus.reachable = true;
  backendStatus.error = '';
  backendStatus.message = message;
  backendStatus.checkedAt = new Date().toLocaleTimeString('zh-CN', { hour12: false });
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

  if (error?.code === 'NETWORK_ERROR' || error?.code === 'INVALID_JSON_RESPONSE' || String(error?.code || '').startsWith('HTTP_')) {
    backendStatus.reachable = false;
    backendStatus.error = error.message;
    backendStatus.message = error.message;
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
  backendStatus.checking = true;
  backendStatus.error = '';
  backendStatus.message = '正在连接后端...';
  try {
    const data = await api.health();
    markBackendHealthy(`后端已就绪 · ${data.project || '定时任务调度'}`);
    return true;
  } catch (error) {
    backendStatus.reachable = false;
    backendStatus.error = error.message;
    backendStatus.message = error.message;
    if (!options.silent) {
      pushToast('error', '后端不可达', error.message);
    }
    return false;
  } finally {
    backendStatus.checking = false;
  }
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
  return row.state !== 'invalid' && !row.pending;
}

function callTaskTitle(row) {
  if (row.state === 'invalid') {
    return '配置错误的任务不能手动触发';
  }
  if (row.pending) {
    return '任务正在运行，不能重复触发';
  }
  if (row.state === 'pause') {
    return '暂停任务也可以手动执行一次';
  }
  if (row.state !== 'true') {
    return '任务未进入调度，也可以手动执行一次';
  }
  return '立即执行一次任务';
}

function buildDateRange(params) {
  if (params.startDate && params.endDate) {
    return [params.startDate, params.endDate];
  }
  return [];
}

async function loadUser() {
  const data = await api.userInfo();
  markBackendHealthy('后端连接正常');
  user.project = data.project || '定时任务调度';
  user.name = data.name || 'Admin';
  user.avatar = data.avatar || '/static/img/head.gif';
}

async function loadDashboard(options = {}) {
  if (!options.silent) {
    dashboard.loading = true;
  }
  dashboard.error = '';
  try {
    const data = await api.dashboard();
    markBackendHealthy('后端连接正常');
    Object.assign(dashboard.summary, data.summary || {});
    Object.assign(dashboard.scheduler, data.scheduler || {});
    dashboard.trend = data.trend || [];
    dashboard.failure_rank = data.failure_rank || [];
    dashboard.recent_runs = data.recent_runs || [];
    Object.assign(dashboard.cpu_timeline, {
      samples: [],
      markers: [],
      current: null,
      current_memory: null,
      sample_interval_seconds: 5,
      retention_hours: 6,
      warning: '',
    }, data.cpu_timeline || {});
    dashboard.warning = data.warning || '';
  } catch (error) {
    await handleRequestFailure(error, { state: dashboard, toastTitle: options.silent ? '' : '总览加载失败' });
  } finally {
    if (!options.silent) {
      dashboard.loading = false;
    }
  }
}

async function handleLogin() {
  const reachable = await checkBackend({ silent: true });
  if (!reachable) {
    pushToast('error', '登录失败', backendStatus.error);
    return;
  }

  loginLoading.value = true;
  try {
    const data = await api.login(loginForm);
    markBackendHealthy('后端连接正常');
    setToken(data.token);
    token.value = data.token;
    await loadUser();
    await Promise.all([loadDashboard(), loadTasks(), loadGroups()]);
    startLiveEvents();
    pushToast('success', '登录成功', '欢迎回来。');
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
  stopLiveEvents();
}

function switchView(nextView) {
  view.value = nextView;
  window.location.hash = nextView;
  mobileNavOpen.value = false;
  syncDashboardPolling();
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
  } else {
    await Promise.all([loadSystemLogs(), loadSystemIds()]);
  }
}

async function loadGroups() {
  try {
    tasks.groups = await api.groups();
    markBackendHealthy('后端连接正常');
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '分组加载失败' });
  }
}

async function loadTasks(resetPage = false, options = {}) {
  if (resetPage) {
    tasks.params.currentPage = 1;
  }
  if (!options.silent) {
    tasks.loading = true;
  }
  tasks.error = '';
  try {
    const data = await api.taskState(tasks.params);
    markBackendHealthy('后端连接正常');
    tasks.items = data.items || [];
    tasks.total = data.total || 0;
  } catch (error) {
    await handleRequestFailure(error, { state: tasks });
  } finally {
    if (!options.silent) {
      tasks.loading = false;
    }
  }
}

function resetTaskFilters() {
  tasks.params.taskid = '';
  tasks.params.taskname = '';
  tasks.params.taskgroup = '';
  loadTasks(true);
}

function setTaskPage(page) {
  tasks.params.currentPage = page;
  loadTasks();
}

function setTaskPageSize(size) {
  tasks.params.pagesize = size;
  tasks.params.currentPage = 1;
  loadTasks();
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
  busy.value = true;
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
    busy.value = false;
  }
}

async function handleCallTask(row) {
  if (!canCallTask(row)) {
    pushToast('error', '无法触发任务', callTaskTitle(row));
    return;
  }
  busy.value = true;
  try {
    const message = await api.callTask({ pid: row.id });
    markBackendHealthy('后端连接正常');
    pushToast('success', '任务已触发', message);
    const refreshes = [loadTasks()];
    if (view.value === 'taskLogs' && taskLogs.params.currentPage === 1) {
      refreshes.push(loadTaskLogs(false, { silent: true }));
    }
    await Promise.all(refreshes);
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '任务触发失败' });
  } finally {
    busy.value = false;
  }
}

async function pauseTask(row) {
  if (row.pending) {
    const confirmed = await requestConfirm({
      title: `任务 ${row.id} 正在执行`,
      message: '暂停只会移除后续调度；如果要立即停止当前进程，请选择强制停止。',
      details: [
        '选择“强制停止”会终止当前进程。',
        '选择“取消”后可以回到列表，仅执行普通暂停。',
      ],
      confirmText: '强制停止',
      cancelText: '仅暂停',
      danger: true,
    });
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
  const seq = ++scheduleLoadSeq;
  schedulePreviewSeq += 1;
  scheduleDialog.open = true;
  scheduleDialog.loading = true;
  scheduleDialog.saving = false;
  scheduleDialog.error = '';
  scheduleDialog.preview = [];
  scheduleDialog.previewError = '';
  scheduleDialog.previewLoading = false;
  scheduleDialog.task = { ...row };
  scheduleDialog.data = null;
  try {
    const data = await api.taskSchedule({
      pid: row.id,
    });
    if (seq !== scheduleLoadSeq || scheduleDialog.task?.id !== row.id) {
      return;
    }
    if (data.pid && data.pid !== row.id) {
      throw new Error(`后端返回 PID ${data.pid} 与当前任务 ${row.id} 不一致，请刷新页面后重试。`);
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

function closeScheduleDialog() {
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
    const data = await api.previewTaskSchedule({
      pid: scheduleDialog.task.id,
      ...form,
    });
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
  if (!scheduleDialog.task) {
    return;
  }
  const taskId = scheduleDialog.task.id;
  scheduleDialog.saving = true;
  scheduleDialog.error = '';
  try {
    const data = await api.updateTaskSchedule({
      pid: taskId,
      ...form,
    });
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
    pushToast('success', '任务配置已保存', `${taskId} 已刷新运行配置。`);
    await Promise.all([loadTasks(), loadDashboard({ silent: true })]);
  } catch (error) {
    scheduleDialog.error = error.message;
    await handleRequestFailure(error, { toastTitle: '调度策略保存失败' });
  } finally {
    scheduleDialog.saving = false;
  }
}

async function openLatestLog(row) {
  try {
    const content = await api.detailLog({ id: row.id });
    markBackendHealthy('后端连接正常');
    showModal(`最新日志：${row.id}`, content || ' ');
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '日志读取失败' });
  }
}

async function reloadTasks(fullReload) {
  const label = fullReload ? '全量重载' : '同步任务';
  if (fullReload) {
    const confirmed = await requestConfirm({
      title: '全量重载调度器',
      message: '全量重载会清空当前调度器内的任务，并按 app/jobs 目录重新注册。',
      details: [
        '正在执行中的子进程不会自动回滚业务数据。',
        '建议在任务低峰期操作，并关注系统日志。',
      ],
      confirmText: '全量重载',
      danger: true,
    });
    if (!confirmed) {
      return;
    }
  }
  tasks.loading = true;
  busy.value = true;
  try {
    const message = await api.reload(fullReload ? { refresh: '1' } : {});
    markBackendHealthy('后端连接正常');
    pushToast('success', label, message);
    await Promise.all([loadTasks(), loadGroups()]);
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: `${label}失败` });
  } finally {
    tasks.loading = false;
    busy.value = false;
  }
}

async function handleUpdateCode() {
  const confirmed = await requestConfirm({
    title: '更新服务器代码',
    message: '该操作会把服务端代码切到配置分支的最新提交，并同步任务列表。',
    details: [
      '更新后如果包含后端代码变更，仍需要按部署流程重启服务。',
      '新增任务会出现在列表里，被删除的任务会从列表和调度器中移除。',
    ],
    confirmText: '更新代码',
    danger: true,
  });
  if (!confirmed) {
    return;
  }
  busy.value = true;
  try {
    const message = await api.updateCode();
    markBackendHealthy('后端连接正常');
    showModal('代码更新结果', message);
    pushToast('success', '代码更新完成', '已同步任务列表。');
    await Promise.all([loadTasks(), loadGroups(), loadDashboard({ silent: true })]);
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '代码更新失败' });
  } finally {
    busy.value = false;
  }
}

function taskLogQueryParams() {
  return {
    taskid: taskLogs.params.taskid,
    taskstate: taskLogs.params.taskstate,
    datetimeval: buildDateRange(taskLogs.params),
    currentPage: taskLogs.params.currentPage,
    pagesize: taskLogs.params.pagesize,
  };
}

async function loadTaskLogs(resetPage = false, options = {}) {
  if (resetPage) {
    taskLogs.params.currentPage = 1;
  }
  if (!options.silent) {
    taskLogs.loading = true;
  }
  taskLogs.error = '';
  try {
    const data = await api.taskLogs(taskLogQueryParams());
    markBackendHealthy('后端连接正常');
    taskLogs.rows = data.data || [];
    taskLogs.total = data.total || 0;
  } catch (error) {
    await handleRequestFailure(error, { state: taskLogs });
  } finally {
    if (!options.silent) {
      taskLogs.loading = false;
    }
  }
}

async function openTaskLog(row) {
  showModal(`任务日志：${row.id}`, '正在加载日志...');
  try {
    const content = await api.taskLogDetail({
      id: row.logid,
      end_time: row.datetime,
      pid: row.id,
    });
    markBackendHealthy('后端连接正常');
    modal.content = formatModalContent(content);
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '日志读取失败' });
    modal.content = error.message || ' ';
  }
}

async function loadTaskIds() {
  try {
    taskLogs.ids = await api.taskIds();
    markBackendHealthy('后端连接正常');
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '任务 ID 加载失败' });
  }
}

function resetTaskLogFilters() {
  taskLogs.params.taskid = '';
  taskLogs.params.taskstate = '';
  taskLogs.params.startDate = '';
  taskLogs.params.endDate = '';
  loadTaskLogs(true);
}

function setTaskLogPage(page) {
  taskLogs.params.currentPage = page;
  loadTaskLogs();
}

function setTaskLogPageSize(size) {
  taskLogs.params.pagesize = size;
  taskLogs.params.currentPage = 1;
  loadTaskLogs();
}

function systemLogQueryParams() {
  return {
    systemids: systemLogs.params.systemids,
    datetimeval: buildDateRange(systemLogs.params),
    currentPage: systemLogs.params.currentPage,
    pagesize: systemLogs.params.pagesize,
  };
}

async function loadSystemLogs(resetPage = false) {
  if (resetPage) {
    systemLogs.params.currentPage = 1;
  }
  systemLogs.loading = true;
  systemLogs.error = '';
  try {
    const data = await api.systemLogs(systemLogQueryParams());
    markBackendHealthy('后端连接正常');
    systemLogs.rows = data.data || [];
    systemLogs.total = data.total || 0;
  } catch (error) {
    await handleRequestFailure(error, { state: systemLogs });
  } finally {
    systemLogs.loading = false;
  }
}

async function loadSystemIds() {
  try {
    systemLogs.ids = await api.systemIds();
    markBackendHealthy('后端连接正常');
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '系统日志 ID 加载失败' });
  }
}

function resetSystemLogFilters() {
  systemLogs.params.systemids = '';
  systemLogs.params.startDate = '';
  systemLogs.params.endDate = '';
  loadSystemLogs(true);
}

function setSystemLogPage(page) {
  systemLogs.params.currentPage = page;
  loadSystemLogs();
}

function setSystemLogPageSize(size) {
  systemLogs.params.pagesize = size;
  systemLogs.params.currentPage = 1;
  loadSystemLogs();
}

function eventSourceUrl() {
  const params = new URLSearchParams({ token: getToken() });
  return `/api/taskinfo/events?${params.toString()}`;
}

function shouldPollDashboard() {
  return Boolean(token.value && view.value === 'dashboard' && document.visibilityState !== 'hidden');
}

async function pollDashboard() {
  if (!shouldPollDashboard() || dashboardPollInFlight) {
    return;
  }
  dashboardPollInFlight = true;
  try {
    await loadDashboard({ silent: true });
  } finally {
    dashboardPollInFlight = false;
  }
}

function syncDashboardPolling() {
  if (shouldPollDashboard()) {
    if (!dashboardPollTimer) {
      dashboardPollTimer = window.setInterval(pollDashboard, DASHBOARD_POLL_MS);
    }
    return;
  }
  stopDashboardPolling();
}

function stopDashboardPolling() {
  if (dashboardPollTimer) {
    window.clearInterval(dashboardPollTimer);
    dashboardPollTimer = null;
  }
  dashboardPollInFlight = false;
}

function startLiveEvents() {
  if (!token.value || eventSource) {
    return;
  }
  clearLiveReconnectTimer();
  eventSource = new EventSource(eventSourceUrl());
  eventSource.onopen = () => {
    clearLiveReconnectTimer();
    liveState.connected = true;
    liveState.lastEvent = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    markBackendHealthy('后端连接正常');
  };
  eventSource.addEventListener('snapshot', handleLiveSnapshot);
  eventSource.addEventListener('stream_error', handleLiveStreamError);
  eventSource.onerror = () => {
    liveState.connected = false;
    liveState.lastEvent = '正在重连';
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    scheduleLiveReconnect();
  };
}

function stopLiveEvents() {
  clearLiveReconnectTimer();
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  liveState.connected = false;
  liveState.lastEvent = '';
  liveTaskSignature = '';
  liveLogSignature = '';
  liveRefreshInFlight = false;
  syncDashboardPolling();
}

function clearLiveReconnectTimer() {
  if (liveReconnectTimer) {
    window.clearTimeout(liveReconnectTimer);
    liveReconnectTimer = null;
  }
}

function scheduleLiveReconnect() {
  if (!token.value || document.visibilityState === 'hidden' || liveReconnectTimer) {
    return;
  }
  liveReconnectTimer = window.setTimeout(() => {
    liveReconnectTimer = null;
    startLiveEvents();
  }, LIVE_RECONNECT_MS);
}

function applyTaskSnapshot(snapshotTasks = []) {
  const byId = new Map(snapshotTasks.map((item) => [item.id, item]));
  tasks.items.forEach((row) => {
    const next = byId.get(row.id);
    if (!next) {
      return;
    }
    row.state = next.state;
    row.pending = next.pending;
    row.next_run_time = next.next_run_time;
  });
}

async function refreshFromLiveSnapshot({ taskChanged, logsChanged }) {
  if (liveRefreshInFlight || document.visibilityState === 'hidden') {
    return;
  }
  liveRefreshInFlight = true;
  try {
    const jobs = [];
    if (view.value === 'dashboard' && (taskChanged || logsChanged)) {
      jobs.push(loadDashboard({ silent: true }));
    }
    if (view.value === 'tasks' && (taskChanged || logsChanged)) {
      jobs.push(loadTasks(false, { silent: true }));
    }
    if (view.value === 'taskLogs' && logsChanged && taskLogs.params.currentPage === 1) {
      jobs.push(loadTaskLogs(false, { silent: true }));
    }
    if (jobs.length) {
      await Promise.all(jobs);
    }
  } finally {
    liveRefreshInFlight = false;
  }
}

function handleLiveSnapshot(event) {
  let payload = {};
  try {
    payload = JSON.parse(event.data || '{}');
  } catch (error) {
    return;
  }
  liveState.connected = true;
  liveState.lastEvent = payload.server_time || new Date().toLocaleTimeString('zh-CN', { hour12: false });
  markBackendHealthy('后端连接正常');

  const nextTaskSignature = JSON.stringify(payload.tasks || []);
  const nextLogSignature = JSON.stringify(payload.logs || {});
  const taskChanged = nextTaskSignature !== liveTaskSignature;
  const logsChanged = nextLogSignature !== liveLogSignature;
  liveTaskSignature = nextTaskSignature;
  liveLogSignature = nextLogSignature;

  applyTaskSnapshot(payload.tasks || []);
  refreshFromLiveSnapshot({ taskChanged, logsChanged });
}

function handleLiveStreamError(event) {
  let payload = {};
  try {
    payload = JSON.parse(event.data || '{}');
  } catch (error) {
    payload = { message: event.data || '实时事件流返回异常' };
  }
  liveState.connected = true;
  liveState.lastEvent = payload.message || '事件流异常';
  backendStatus.reachable = true;
  backendStatus.error = '';
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

watch(token, (nextToken) => {
  if (nextToken) {
    startLiveEvents();
  } else {
    stopLiveEvents();
  }
  syncDashboardPolling();
});

window.addEventListener('hashchange', () => {
  const nextView = window.location.hash.replace('#', '');
  if (navItems.some((item) => item.id === nextView)) {
    view.value = nextView;
  }
});

onMounted(async () => {
  applyTheme();
  document.addEventListener('visibilitychange', handleVisibilityChange);
  if (!navItems.some((item) => item.id === view.value)) {
    view.value = 'dashboard';
  }

  const reachable = await checkBackend({ silent: true });
  ready.value = true;

  if (!reachable || !token.value) {
    return;
  }

  try {
    await loadUser();
    await Promise.all([loadDashboard(), loadTasks(), loadGroups()]);
    startLiveEvents();
    syncDashboardPolling();
  } catch (error) {
    clearToken();
    token.value = '';
    pushToast('error', '会话已失效', error.message);
  }
});

onUnmounted(() => {
  stopLiveEvents();
  stopDashboardPolling();
  document.removeEventListener('visibilitychange', handleVisibilityChange);
});
</script>

