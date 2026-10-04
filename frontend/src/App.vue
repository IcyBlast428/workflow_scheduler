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

  <main v-else-if="!token" class="login-screen" :style="{ '--login-radius': `${LOGIN_CORNER_RADIUS}px` }">
    <LoginBackdrop @scene-change="loginVisual = $event" />
    <LiquidGlassPanel :snapshot="loginVisual">
      <div class="login-brief">
        <div class="login-brand-row"><BrandLogo /><span>WORKFLOW SCHEDULER</span></div>
        <h1>定时任务调度</h1>
        <p>面向内网运维任务的调度控制台，集中管理任务扫描、暂停启动、运行日志与系统异常记录。</p>
        <div class="login-workflow" aria-hidden="true">
          <div class="login-workflow-line" />
          <div class="login-workflow-step"><span><svg viewBox="0 0 24 24" fill="none"><rect x="4" y="4" width="6" height="6" rx="1.5"/><rect x="14" y="4" width="6" height="6" rx="1.5"/><rect x="9" y="14" width="6" height="6" rx="1.5"/><path d="M7 10v2h10v-2M12 12v2"/></svg></span><strong>编排</strong><small>组织任务</small></div>
          <div class="login-workflow-step"><span><svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8"/><path d="M12 7v5l-3 2"/></svg></span><strong>调度</strong><small>按时触发</small></div>
          <div class="login-workflow-step"><span><svg viewBox="0 0 24 24" fill="none"><path d="m7 12 3 3 7-7"/><rect x="4" y="4" width="16" height="16" rx="4"/></svg></span><strong>执行</strong><small>记录结果</small></div>
        </div>
        <p class="login-tagline">让每一次执行，都有迹可循。</p>
      </div>
      <form class="login-form" @submit.prevent="handleLogin">
        <div class="login-form-head">
          <div>
            <h2>登录控制台</h2>
            <p class="hint">使用已分配的账户登录。</p>
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
        <button class="btn primary" type="submit" aria-label="登录" :disabled="loginLoading || !backendStatus.reachable">
          <span class="btn-icon">></span>
          {{ loginLoading ? '登录中...' : '登录' }}
        </button>
      </form>
    </LiquidGlassPanel>
  </main>

  <div v-else class="app-shell">
    <aside class="sidebar" :class="{ open: mobileNavOpen }">
      <div class="brand">
        <BrandLogo />
        <div class="brand-copy">
          <h1>{{ user.project || '定时任务调度' }}</h1>
          <span>Workflow Scheduler</span>
        </div>
      </div>
      <button class="btn icon-only mobile-menu" type="button" title="菜单" @click="mobileNavOpen = !mobileNavOpen">≡</button>
      <nav class="nav">
        <button
          v-for="item in visibleNavItems"
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
          <button v-if="canManage" class="btn warning" type="button" :disabled="busy" @click="handleUpdateCode">
            <span class="btn-icon">^</span>
            检查更新
          </button>
          <div class="status-chip" :class="backendStatus.reachable ? 'online' : 'offline'">
            <strong>{{ backendStatus.reachable ? '后端正常' : '后端异常' }}</strong>
            <span>{{ backendStatus.checkedAt || '未检测' }}</span>
          </div>
          <div v-if="!['dashboard', 'matrix', 'admin', 'packages'].includes(view)" class="status-chip" :class="liveState.connected ? 'online' : 'offline'">
            <strong>{{ liveState.connected ? '实时同步' : '实时断开' }}</strong>
            <span>{{ liveState.lastEvent || '等待连接' }}</span>
          </div>
          <UserMenu :name="user.name || 'Admin'" :avatar="user.avatar" @logout="handleLogout" />
        </div>
      </header>

      <section class="content" :class="{ 'dashboard-content': view === 'dashboard' }">
        <div v-if="backendStatus.error" class="inline-alert danger content-alert">
          <strong>当前后端连接异常</strong>
          <span>{{ backendStatus.error }}</span>
          <button class="btn" type="button" @click="refreshActiveView()">重新检测</button>
        </div>

        <template v-if="view === 'dashboard'">
          <LoadingStatus :active="dashboard.loading" label="正在更新总览…" />
          <div v-if="dashboard.error" class="error-state">{{ dashboard.error }}</div>
          <template v-if="!dashboard.error || dashboard.loaded">
            <DashboardSummary :summary="dashboard.summary" :failures="dashboard.failure_rank" :recent="dashboard.recent_runs" @tasks="showFilteredTasks" @detail="detailPid = $event" />
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

        <template v-else-if="view === 'matrix'">
          <ExecutionMatrix :user-key="user.name" @task="detailPid = $event" @execution="openExecution" @logs="openMatrixLogs" />
        </template>

        <template v-else-if="view === 'tasks'">
          <div class="summary-grid">
            <div class="metric-card">
              <span>任务总数</span>
              <strong>{{ tasks.total }}</strong>
            </div>
            <div class="metric-card">
              <span>本页调度已启用</span>
              <strong>{{ taskSummary.running }}</strong>
            </div>
            <div class="metric-card">
              <span>本页有活动实例</span>
              <strong>{{ taskSummary.pending }}</strong>
            </div>
            <div class="metric-card">
              <span>本页配置异常</span>
              <strong>{{ taskSummary.invalid }}</strong>
            </div>
            <div class="metric-card">
              <span>本页连续失败合计</span>
              <strong>{{ taskSummary.failed }}</strong>
            </div>
          </div>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h2>任务列表</h2>
                <p>查看已发布任务和 Git 任务，维护调度策略与运行状态。</p>
              </div>
              <div class="filter-actions">
                <button v-if="canManage" class="btn primary" type="button" @click="openPackages('')">任务发布 / 新增</button>
                <button v-if="canManage" class="btn" type="button" :disabled="tasks.loading" @click="reloadTasks(false)">
                  <span class="btn-icon">+</span>
                  同步任务
                </button>
                <button v-if="canManage" class="btn danger" type="button" :disabled="tasks.loading" @click="reloadTasks(true)">
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
              <div class="form-row"><label for="task-status">任务状态</label><select id="task-status" v-model="tasks.params.status" class="select"><option value="">全部状态</option><option value="active">有活动实例</option><option value="failed">最近结果异常</option><option value="invalid">配置异常</option><option value="enabled">调度已启用</option></select></div>
              <div class="form-row"><label for="task-owner">负责人</label><input id="task-owner" v-model.trim="tasks.params.owner" class="input" placeholder="负责人关键字"></div>
              <div class="filter-actions">
                <button class="btn primary" type="submit">
                  <span class="btn-icon">?</span>
                  搜索
                </button>
                <button class="btn" type="button" @click="resetTaskFilters">清空</button>
                <label class="checkbox-row"><input v-model="onlyFavorites" type="checkbox" @change="loadTasks(true)">仅看收藏</label>
              </div>
            </form>
            <div class="batch-toolbar"><span class="selection-count">已选择 <strong>{{ selectedTasks.length }}</strong> 个任务</span><div class="filter-actions"><button v-if="canOperate" class="btn" :disabled="!selectedTasks.length || batchBusy" @click="batchTaskAction('pause')">批量暂停调度</button><button v-if="canOperate" class="btn" :disabled="!selectedTasks.length || batchBusy" @click="batchTaskAction('start')">批量启用调度</button><button class="btn" :disabled="!selectedTasks.length" @click="selectedTasks = []">取消选择</button></div></div>
            <LoadingStatus :active="tasks.loading" label="正在更新任务列表…" />
            <div v-if="tasks.error" class="error-state">{{ tasks.error }}</div>
            <div v-if="!tasks.items.length && !tasks.error" class="empty-state">
              <strong>{{ tasks.loading ? '正在读取任务' : '没有匹配的任务' }}</strong>
              <span>{{ tasks.loading ? '正在更新结果，请稍候。' : '可以清空筛选条件，或点击“同步任务”同步 app/jobs 目录。' }}</span>
            </div>
            <TaskTable
              v-else-if="tasks.items.length"
              :rows="tasks.items"
              :busy="busy"
              :pending-actions="pendingActions"
              :can-operate="canOperate"
              :can-manage="canManage"
              :favorites="favorites"
              :selected="selectedTasks"
              @favorite="toggleFavorite"
              @select="toggleSelected"
              @detail="detailPid = $event.id"
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
                <p>默认查看最近 7 天。历史记录可按任务和日期查询，每次日期范围不超过 93 天。</p>
              </div>
            </div>
            <div v-if="matrixLogRange.length" class="inline-note">来自执行矩阵：{{ matrixLogRange[0] }} — {{ matrixLogRange[1] }}。搜索或清空可恢复按日期查询。</div>
            <form class="filter-grid logs" @submit.prevent="searchTaskLogs">
              <div class="form-row">
                <label for="task-log-scope">查询范围</label>
                <select id="task-log-scope" v-model="taskLogs.params.scope" class="select">
                  <option value="online">近期记录</option>
                  <option value="archive">归档记录</option>
                  <option value="all">近期与归档</option>
                </select>
              </div>
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
                  <option value="已停止">已停止</option>
                  <option value="重启中断">重启中断</option>
                  <option value="超时/终止">超时/终止</option>
                  <option value="并发跳过">并发跳过</option>
                  <option value="错过调度">错过调度</option>
                </select>
              </div>
              <div class="form-row">
                <label for="task-log-start">开始日期</label>
                <input id="task-log-start" v-model="taskLogs.params.startDate" class="input" type="date" required>
              </div>
              <div class="form-row">
                <label for="task-log-end">结束日期</label>
                <input id="task-log-end" v-model="taskLogs.params.endDate" class="input" type="date" required>
              </div>
              <div class="filter-actions">
                <button class="btn primary" type="submit">
                  <span class="btn-icon">?</span>
                  搜索
                </button>
                <button class="btn" type="button" @click="resetTaskLogFilters">清空</button>
              </div>
            </form>
            <LoadingStatus :active="taskLogs.loading" label="正在更新调度日志…" />
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
              :exact="false"
              :has-more="taskLogs.hasMore"
              :busy="taskLogs.loading"
              @page="setTaskLogPage"
              @page-size="setTaskLogPageSize"
            />
          </section>
        </template>

        <template v-else-if="view === 'packages' && canManage"><TaskPackageManager :confirm="requestConfirm" :initial-pid="packagePid" @detail="detailPid = $event" @changed="refreshPackageTasks" /></template>
        <template v-else-if="view === 'admin' && canManage"><AdminPanel /></template>
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
            <LoadingStatus :active="systemLogs.loading" label="正在更新系统日志…" />
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
              :exact="false"
              :has-more="systemLogs.hasMore"
              @page="setSystemLogPage"
              @page-size="setSystemLogPageSize"
            />
          </section>
        </template>
      </section>
    </div>
  </div>

  <div v-if="modal.open" class="modal-backdrop" @click.self="closeModal">
    <section v-glass class="modal glass-surface glass-floating">
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
    <div v-for="toast in toasts" :key="toast.id" v-glass class="toast glass-surface glass-floating" :class="toast.type">
      <strong>{{ toast.title }}</strong>
      <span>{{ toast.message }}</span>
    </div>
  </div>

  <ConfirmDialog :model-value="confirmState" @resolve="resolveConfirm" />
  <TaskDetailDialog :pid="detailPid" :can-manage="canManage" @close="detailPid = ''" @execution="openExecution" @confirm-restore="confirmRestore" @packages="openPackages" />
  <ExecutionDialog :run-id="executionRunId" :can-operate="canOperate" :retrying="retryingExecution" @retry="retryExecution" @close="executionRunId = ''" />
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
import { computed, onMounted, onUnmounted, reactive, ref, shallowRef, watch } from 'vue';
import BrandLogo from './components/BrandLogo.vue';
import CursorLight from './components/CursorLight.vue';
import LoginBackdrop from './components/LoginBackdrop.vue';
import LiquidGlassPanel from './components/LiquidGlassPanel.vue';
import { LOGIN_CORNER_RADIUS } from './loginBackdropScene';
import UserMenu from './components/UserMenu.vue';
import LoadingStatus from './components/LoadingStatus.vue';
import { api, clearToken, getToken, setToken } from './api';
import { scheduleRequest } from './scheduleForm';
import ConfirmDialog from './components/ConfirmDialog.vue';
import CpuTimelineChart from './components/CpuTimelineChart.vue';
import LogTable from './components/LogTable.vue';
import Pagination from './components/Pagination.vue';
import ScheduleDialog from './components/ScheduleDialog.vue';
import { useTaskWorkspace } from './composables/useTaskWorkspace';
import { useLogWorkspace, recentLogDates } from './composables/useLogWorkspace';
import { useDashboardWorkspace } from './composables/useDashboardWorkspace';
import TaskTable from './components/TaskTable.vue';
import TaskDetailDialog from './components/TaskDetailDialog.vue';
import ExecutionDialog from './components/ExecutionDialog.vue';
import AdminPanel from './components/AdminPanel.vue';
import TaskPackageManager from './components/TaskPackageManager.vue';
import DashboardSummary from './components/DashboardSummary.vue';
import ExecutionMatrix from './components/ExecutionMatrix.vue';
import { canTrigger } from './executionLabels';
import { useConfirm } from './composables/useConfirm';
const loginVisual = shallowRef(null);

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
    id: 'matrix', label:'执行矩阵', iconPaths:['M3 7l9-4 9 4-9 4z','M3 12l9 4 9-4','M3 17l9 4 9-4'], description:'按任务分类查看当日执行轨迹。',
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
  { id:'packages', label:'任务发布', iconPaths:['M3 7l9-4 9 4-9 4z','M3 7v10l9 4 9-4V7','M12 11v10'], description:'任务包上传、发布、版本回滚与回收站。' },
  { id:'admin', label:'账户与审计', iconPaths:['M4 6h16','M4 12h16','M4 18h16'], description:'账户权限与操作记录。' },
];

const ready = ref(false);
const token = ref(getToken());
const view = ref(window.location.hash.replace('#', '') || 'dashboard');
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
let eventSource = null;
let livePollInFlight = false;
let dashboardPollTimer = null;
let dashboardPollInFlight = false;
let liveRefreshInFlight = false;
let scheduleLoadSeq = 0;
let schedulePreviewSeq = 0;
let liveTaskSignature = '';
let liveLogSignature = '';
const DASHBOARD_POLL_MS = 5000;

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
  roles: [],
});
const canManage = computed(() => user.roles.includes('admin'));
const canOperate = computed(() => canManage.value || user.roles.includes('operator'));
const visibleNavItems = computed(() => navItems.filter(item => !['admin','packages'].includes(item.id) || canManage.value));

const { tasks, favorites, onlyFavorites, selectedTasks, batchBusy, saveFilters, toggleFavorite, toggleSelected } = useTaskWorkspace(() => user.name);
const liveState = reactive({
  connected: false,
  lastEvent: '',
});

const dashboard = useDashboardWorkspace();
const { taskLogs, systemLogs } = useLogWorkspace();
let taskLogRequestSerial = 0;
const matrixLogRange = ref([]);
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

  if (error?.code === 'NETWORK_ERROR' || error?.code === 'INVALID_JSON_RESPONSE' || String(error?.code || '').startsWith('HTTP_5')) {
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
  user.roles = data.roles || [];
  if (data.csrf_token) { setToken(data.csrf_token); token.value = data.csrf_token; }
  if (['admin','packages'].includes(view.value) && !canManage.value) switchView('tasks');
}

async function loadDashboard(options = {}) {
  if (!options.silent) {
    dashboard.loading = true;
  }
  dashboard.error = '';
  try {
    const data = await api.dashboard(options.silent ? { after: dashboard.cpu_timeline.cursor || '' } : {});
    dashboard.loaded = true;
    markBackendHealthy('后端连接正常');
    Object.assign(dashboard.summary, data.summary || {});
    Object.assign(dashboard.scheduler, data.scheduler || {});
    dashboard.trend = data.trend || [];
    dashboard.failure_rank = data.failure_rank || [];
    dashboard.recent_runs = data.recent_runs || [];
    const incoming = data.cpu_timeline || {};
    if (incoming.incremental) {
      const cutoff = Date.now() - 6 * 60 * 60 * 1000;
      const merged = new Map([...dashboard.cpu_timeline.samples, ...(incoming.samples || [])].map(item => [item.time, item]));
      incoming.samples = [...merged.values()].filter(item => new Date(item.time.replace(' ', 'T')).getTime() >= cutoff).sort((a,b) => a.time.localeCompare(b.time));
    }
    Object.assign(dashboard.cpu_timeline, {
      samples: [],
      markers: [],
      current: null,
      current_memory: null,
      sample_interval_seconds: 5,
      retention_hours: 6,
      warning: '',
    }, incoming);
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
    setToken(data.csrf_token);
    token.value = data.csrf_token;
    await loadUser();
    await Promise.all([loadDashboard(), loadTasks(), loadGroups()]);
    startLiveEvents();
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

function openPackages(pid) { detailPid.value = ''; packagePid.value = pid; switchView('packages'); }
async function refreshPackageTasks() { await Promise.all([loadTasks(),loadGroups()]); }

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

async function loadGroups() {
  try {
    tasks.groups = await api.groups();
    markBackendHealthy('后端连接正常');
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '分组加载失败' });
  }
}

let taskRequestSerial = 0;
async function loadTasks(resetPage = false, options = {}) {
  const serial = ++taskRequestSerial;
  if (resetPage) {
    tasks.params.currentPage = 1;
  }
  if (!options.silent) {
    tasks.loading = true;
  }
  tasks.error = '';
  try {
    saveFilters();
    if (onlyFavorites.value && !favorites.value.length) { tasks.items = []; tasks.total = 0; return; }
    const data = await api.taskState({...tasks.params, ids:onlyFavorites.value ? favorites.value : []});
    if (serial !== taskRequestSerial) return;
    markBackendHealthy('后端连接正常');
    tasks.items = data.items || [];
    tasks.total = data.total || 0;
  } catch (error) {
    if (serial === taskRequestSerial) await handleRequestFailure(error, { state: tasks });
  } finally {
    if (serial === taskRequestSerial && !options.silent) {
      tasks.loading = false;
    }
  }
}

function resetTaskFilters() {
  tasks.params.taskid = '';
  tasks.params.taskname = '';
  tasks.params.taskgroup = '';
  tasks.params.status = '';
  tasks.params.owner = '';
  onlyFavorites.value = false;
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

async function batchTaskAction(action) {
  if (batchBusy.value) return;
  batchBusy.value = true;
  try {
    const ids = [...selectedTasks.value];
    const { preview } = await api.batch({ids,action,preview:true});
    const label = action === 'pause' ? '暂停调度' : '启用调度';
    const confirmed = await requestConfirm({title:`批量${label}`,message:`将对 ${preview.length} 个任务${label}。`,
      details:[...preview.map(item => `${item.name} (${item.pid}) · 活动 ${item.active}`),'正在执行的实例继续运行；本操作只改变后续调度。'],confirmText:label,danger:true});
    if (!confirmed) return;
    const data = await api.batch({ids,action,versions:Object.fromEntries(preview.map(item => [item.pid,item.version]))});
    const failures = data.results.filter(item => !item.ok);
    selectedTasks.value = failures.map(item => item.pid);
    pushToast(failures.length ? 'error' : 'success','批量操作结果',failures.length ? failures.map(item => `${item.pid}：${item.message}`).join('；') : `${data.results.length} 个任务已${label}`);
    await loadTasks();
  } catch(error) { await handleRequestFailure(error,{toastTitle:'批量操作失败'}); }
  finally { batchBusy.value = false; }
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
  const keepData = scheduleDialog.open && scheduleDialog.task?.id === row.id && scheduleDialog.data;
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
    const data = await api.previewTaskSchedule(scheduleRequest(scheduleDialog.task.id, form));
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
    pushToast(data.application?.status === 'failed' ? 'error' : 'success', '任务配置已保存', data.application?.status === 'failed' ? `保存成功，但生效失败：${data.application.message}。请刷新任务重新应用。` : `${taskId} 已生效。`);
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
    title: '检查服务器版本',
    message: '从远端读取最新提交，查看当前服务是否需要发布新版本。',
    details: [
      '检查不会修改正在运行的代码或调度配置。',
      '发现新版本后，请按部署流程发布并重启服务。',
    ],
    confirmText: '检查更新',
    danger: false,
  });
  if (!confirmed) {
    return;
  }
  busy.value = true;
  try {
    const message = await api.updateCode();
    markBackendHealthy('后端连接正常');
    showModal('版本检查结果', message);
    pushToast('success', '版本检查完成', '请查看检查结果。');
    await Promise.all([loadTasks(), loadGroups(), loadDashboard({ silent: true })]);
  } catch (error) {
    await handleRequestFailure(error, { toastTitle: '检查更新失败' });
  } finally {
    busy.value = false;
  }
}

function taskLogQueryParams() {
  return {
    scope: taskLogs.params.scope,
    cursor: taskLogs.cursors[taskLogs.params.currentPage-1] || '',
    taskid: taskLogs.params.taskid,
    taskstate: taskLogs.params.taskstate,
    datetimeval: matrixLogRange.value.length ? matrixLogRange.value : buildDateRange(taskLogs.params),
    currentPage: taskLogs.params.currentPage,
    pagesize: taskLogs.params.pagesize,
  };
}

async function loadTaskLogs(resetPage = false, options = {}) {
  if (resetPage) {
    taskLogs.params.currentPage = 1;
    taskLogs.cursors = [''];
  }
  const serial = ++taskLogRequestSerial;
  if (!options.silent) {
    taskLogs.loading = true;
  }
  taskLogs.error = '';
  try {
    const data = await api.taskLogs(taskLogQueryParams());
    if (serial !== taskLogRequestSerial) return;
    markBackendHealthy('后端连接正常');
    taskLogs.rows = data.data || [];
    taskLogs.total = data.total || 0;
    taskLogs.hasMore = Boolean(data.has_more);
    taskLogs.nextCursor = data.next_cursor || '';
  } catch (error) {
    if (serial !== taskLogRequestSerial) return;
    await handleRequestFailure(error, { state: taskLogs });
  } finally {
    if (!options.silent && serial === taskLogRequestSerial) {
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
  matrixLogRange.value = [];
  const dates = recentLogDates();
  taskLogs.params.scope = 'online';
  taskLogs.params.taskid = '';
  taskLogs.params.taskstate = '';
  taskLogs.params.startDate = dates.start;
  taskLogs.params.endDate = dates.end;
  loadTaskLogs(true);
}

function searchTaskLogs() {
  matrixLogRange.value = [];
  loadTaskLogs(true);
}

function setTaskLogPage(page) {
  if (taskLogs.loading) return;
  if (page > taskLogs.params.currentPage) {
    if (!taskLogs.nextCursor) return;
    taskLogs.cursors[page-1] = taskLogs.nextCursor;
  }
  taskLogs.params.currentPage = page;
  loadTaskLogs();
}

function setTaskLogPageSize(size) {
  taskLogs.params.pagesize = size;
  taskLogs.params.currentPage = 1;
  loadTaskLogs(true);
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
    systemLogs.hasMore = Boolean(data.has_more);
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

async function pollLiveEvents() {
  if (!token.value || livePollInFlight || ['dashboard','matrix','admin','packages'].includes(view.value) || document.visibilityState === 'hidden') {
    return;
  }
  livePollInFlight = true;
  try {
    const payload = await api.events();
    handleLiveSnapshot({ data: JSON.stringify(payload) });
  } catch (error) {
    liveState.connected = false;
    liveState.lastEvent = '正在重连';
    handleRequestFailure(error);
  } finally {
    livePollInFlight = false;
  }
}

function startLiveEvents() {
  if (!token.value || eventSource) return;
  eventSource = window.setInterval(pollLiveEvents, 5000);
  pollLiveEvents();
}

function stopLiveEvents() {
  if (eventSource) {
    window.clearInterval(eventSource);
    eventSource = null;
  }
  liveState.connected = false;
  liveState.lastEvent = '';
  liveTaskSignature = '';
  liveLogSignature = '';
  liveRefreshInFlight = false;
  syncDashboardPolling();
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
    row.running_instances = next.running_instances;
    row.max_instances = next.max_instances;
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

    if (view.value === 'tasks' && (taskChanged || logsChanged)) {
      jobs.push(loadTasks(false, { silent: true }));
    }
    if (view.value === 'taskLogs' && logsChanged && taskLogs.params.currentPage === 1 && !taskLogs.loading && taskLogs.params.scope !== 'archive' && taskLogs.params.endDate === recentLogDates().end) {
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

function openExecution(runId) { detailPid.value = ''; executionRunId.value = runId; }
function openMatrixLogs(record) {
  taskLogs.params.taskid = record.pid;
  taskLogs.params.scope = 'online';
  taskLogs.params.startDate = record.start_time.slice(0,10);
  taskLogs.params.endDate = record.end_time.slice(0,10);
  taskLogs.params.taskstate = '';
  matrixLogRange.value = [record.query_start, record.query_end];
  switchView('taskLogs');
  loadTaskLogs(true);
}
async function retryExecution(record) {
  if (retryingExecution.value) return;
  const confirmed = await requestConfirm({title:'再次执行任务',message:`手动执行 ${record.pid}，会生成新的执行记录。`,details:['请先确认上次执行是否已写入业务数据；系统不会自动重试或补跑重启前的执行。'],confirmText:'再执行一次',danger:true});
  if (!confirmed) return;
  retryingExecution.value = true;
  try { const result = await api.callTask({pid:record.pid}); openExecution(result.run_id); await loadTasks(); }
  catch (error) { await handleRequestFailure(error,{toastTitle:'再次执行失败'}); }
  finally { retryingExecution.value = false; }
}
function showFilteredTasks(status) { tasks.params.status = status; switchView('tasks'); loadTasks(true); }
async function confirmRestore(payload) {
  const confirmed = await requestConfirm({title:'恢复调度配置',message:`将 ${payload.pid} 恢复为历史版本 ${payload.restore_version}，并生成新版本。`,details:['会沿用所选版本的调度启用状态；正在执行的实例继续运行。'],confirmText:'恢复配置',danger:true});
  if (!confirmed) return;
  try {
    const result = await api.restore({pid:payload.pid,version:payload.version,restore_version:payload.restore_version});
    pushToast(result.application?.status === 'failed' ? 'error' : 'success','配置已恢复',result.application?.message || '已生成新版本并应用调度。');
    payload.done(); loadTasks();
  } catch (error) { await handleRequestFailure(error,{toastTitle:'恢复配置失败'}); }
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
    await Promise.all([loadDashboard(), loadTasks(), loadGroups()]);
    startLiveEvents();
    syncDashboardPolling();
  } catch (error) {
    clearToken();
    token.value = '';
    if (hadToken || !isAuthError(error)) pushToast('error', '登录状态检查失败', error.message);
  }
});

onUnmounted(() => {
  stopLiveEvents();
  stopDashboardPolling();
  document.removeEventListener('visibilitychange', handleVisibilityChange);
});
</script>

