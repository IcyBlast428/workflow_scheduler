import { reactive, watch, onScopeDispose } from 'vue';
import {useRefreshLoop} from './useRefreshLoop.js';
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
  let livePollInFlight = false,
    liveRefreshInFlight = false,
    liveTaskSignature = '',
    liveLogSignature = '',
    logsDirty = false,
    tasksDirty = false,
    epoch = 0,
    stopped = false;
  async function pollLiveEvents() {
    if (
      !token.value ||
      livePollInFlight ||
      ['dashboard', 'matrix', 'admin', 'packages', 'connections'].includes(view.value) ||
      document.visibilityState === 'hidden'
    ) {
      return;
    }
    livePollInFlight = true;
    const generation = epoch;
    try {
      const payload = await api.events();
      if (stopped || generation !== epoch) return;
      return await handleLiveSnapshot({ data: JSON.stringify(payload) });
    } catch (error) {
      if (stopped || generation !== epoch) return;
      liveState.connected = false;
      liveState.lastEvent = '正在重连';
      await handleRequestFailure(error);
      return false;
    } finally {
      if (generation === epoch) livePollInFlight = false;
    }
  }

  const polling=useRefreshLoop({load:pollLiveEvents,enabled:()=>Boolean(token.value && ['tasks','taskLogs','systemLogs'].includes(view.value)),immediate:false});
  function startLiveEvents(){polling.start(true);}

  function stopLiveEvents() {
    epoch++;
    livePollInFlight = false;
    polling.stop();
    liveState.connected = false;
    liveState.lastEvent = '';
    liveTaskSignature = '';
    liveLogSignature = '';
    logsDirty = false;
    tasksDirty = false;
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
    if(logsChanged)logsDirty=true;
    if(taskChanged || logsChanged)tasksDirty=true;
    if (liveRefreshInFlight || document.visibilityState === 'hidden') {
      return;
    }
    liveRefreshInFlight = true;
    try {
      const jobs = [];

      if (view.value === 'tasks' && tasksDirty) {
        tasksDirty=false;
        jobs.push(loadTasks(false, { silent: true }));
      }
      if (
        view.value === 'taskLogs' &&
        logsDirty &&
        taskLogs.loaded &&
        !taskLogs.loading &&
        taskLogs.params.scope !== 'archive' &&
        taskLogs.params.endDate === recentLogDates().end
      ) {
        logsDirty=false;
        jobs.push(loadTaskLogs(false, { silent: true, buffer: true }));
      }
      if (jobs.length) {
        await Promise.all(jobs);
        return !tasks.error && !taskLogs.refreshError;
      }
    } finally {
      if(taskLogs.refreshError)logsDirty=true;
      if(tasks.error)tasksDirty=true;
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
    return refreshFromLiveSnapshot({ taskChanged, logsChanged });
  }
  watch(token, (value) => (value ? startLiveEvents() : stopLiveEvents()));
  onScopeDispose(() => {
    stopped = true;
    stopLiveEvents();
  });
  return { liveState, startLiveEvents, stopLiveEvents };
}
