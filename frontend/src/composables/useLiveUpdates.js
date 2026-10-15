import { reactive, watch, onScopeDispose } from 'vue';
import { api } from '../api.js';
import { recentLogDates } from './useLogWorkspace.js';
export function useLiveUpdates({
  token,
  view,
  tasks,
  taskLogs,
  loadTasks,
  loadTaskLogs,
  markBackendHealthy,
  handleRequestFailure,
}) {
  const liveState = reactive({ connected: false, lastEvent: '' });
  let eventSource = null,
    livePollInFlight = false,
    liveRefreshInFlight = false,
    liveTaskSignature = '',
    liveLogSignature = '',
    epoch = 0,
    stopped = false;
  async function pollLiveEvents() {
    if (
      !token.value ||
      livePollInFlight ||
      ['dashboard', 'matrix', 'admin', 'packages'].includes(view.value) ||
      document.visibilityState === 'hidden'
    ) {
      return;
    }
    livePollInFlight = true;
    const generation = epoch;
    try {
      const payload = await api.events();
      if (stopped || generation !== epoch) return;
      handleLiveSnapshot({ data: JSON.stringify(payload) });
    } catch (error) {
      if (stopped || generation !== epoch) return;
      liveState.connected = false;
      liveState.lastEvent = '正在重连';
      handleRequestFailure(error);
    } finally {
      if (generation === epoch) livePollInFlight = false;
    }
  }

  function startLiveEvents() {
    if (!token.value || eventSource) return;
    eventSource = window.setInterval(pollLiveEvents, 5000);
    pollLiveEvents();
  }

  function stopLiveEvents() {
    epoch++;
    livePollInFlight = false;
    if (eventSource) {
      window.clearInterval(eventSource);
      eventSource = null;
    }
    liveState.connected = false;
    liveState.lastEvent = '';
    liveTaskSignature = '';
    liveLogSignature = '';
    liveRefreshInFlight = false;
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
      if (
        view.value === 'taskLogs' &&
        logsChanged &&
        taskLogs.params.currentPage === 1 &&
        !taskLogs.loading &&
        taskLogs.params.scope !== 'archive' &&
        taskLogs.params.endDate === recentLogDates().end
      ) {
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
    liveState.lastEvent =
      payload.server_time ||
      new Date().toLocaleTimeString('zh-CN', { hour12: false });
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
  watch(token, (value) => (value ? startLiveEvents() : stopLiveEvents()));
  onScopeDispose(() => {
    stopped = true;
    stopLiveEvents();
  });
  return { liveState, startLiveEvents, stopLiveEvents };
}
