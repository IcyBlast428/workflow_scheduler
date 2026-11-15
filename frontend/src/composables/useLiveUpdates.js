import { watch, onScopeDispose } from 'vue';
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
      return await handleLiveSnapshot(payload);
    } catch (error) {
      if (stopped || generation !== epoch) return;
      await handleRequestFailure(error);
      return false;
    } finally {
      if (generation === epoch) livePollInFlight = false;
    }
  }

  const polling=useRefreshLoop({load:pollLiveEvents,enabled:()=>Boolean(token.value && ['tasks','taskLogs'].includes(view.value)),key:()=>view.value,onResume:()=>{if(view.value==='tasks')tasksDirty=true;if(view.value==='taskLogs')logsDirty=true;}});
  function startLiveEvents(){polling.start(true);}

  function stopLiveEvents() {
    epoch++;
    livePollInFlight = false;
    polling.stop();
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

      if (view.value === 'tasks' && tasksDirty && !tasks.loading) {
        tasksDirty=false;
        jobs.push(loadTasks(false, { silent: tasks.loaded === true }));
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

  function handleLiveSnapshot(payload) {
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
  watch(token, value => { if (!value) stopLiveEvents(); });
  onScopeDispose(() => {
    stopped = true;
    stopLiveEvents();
  });
  return { startLiveEvents, stopLiveEvents };
}
