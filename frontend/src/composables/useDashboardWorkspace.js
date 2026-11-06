import { reactive, watch, onScopeDispose } from 'vue';
import { api } from '../api.js';
import {useRefreshLoop} from './useRefreshLoop.js';
import { timestamp } from '../timebase.js';
export function useDashboardWorkspace({
  token,
  view,
  markBackendHealthy,
  handleRequestFailure,
}) {
  let serial = 0, pending = null;
  const dashboard = reactive({
    loading: false,
    loaded: false,
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
    scheduler: { enabled: false, control_url: '', job_count: 0 },
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
  function loadDashboard(options = {}) {
    if (!options.silent) dashboard.loading=true;
    if (pending) return pending;
    const request=fetchDashboard(options);
    pending=request;
    const clear=()=>{if(pending===request){pending=null;dashboard.loading=false;}};
    request.then(clear,clear);
    return request;
  }
  async function fetchDashboard(options = {}) {
    const current = ++serial;
    if (!options.silent) {
      dashboard.loading = true;
    }
    dashboard.error = '';
    try {
      const data = await api.dashboard(
        options.silent ? { after: dashboard.cpu_timeline.cursor || '' } : {},
      );
      if (current !== serial) return;
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
        const merged = new Map(
          [...dashboard.cpu_timeline.samples, ...(incoming.samples || [])].map(
            (item) => [item.time, item],
          ),
        );
        incoming.samples = [...merged.values()]
          .filter((item) => timestamp(item.time) >= cutoff)
          .sort((a, b) => a.time.localeCompare(b.time));
      }
      Object.assign(
        dashboard.cpu_timeline,
        {
          samples: [],
          markers: [],
          current: null,
          current_memory: null,
          sample_interval_seconds: 5,
          retention_hours: 6,
          warning: '',
        },
        incoming,
      );
      dashboard.warning = data.warning || '';
      return true;
    } catch (error) {
      if (current !== serial) return;
      await handleRequestFailure(error, {
        state: dashboard,
        toastTitle: options.silent ? '' : '总览加载失败',
      });
      return false;
    } finally {
      if (current === serial && !options.silent) {
        dashboard.loading = false;
      }
    }
  }

  const polling=useRefreshLoop({load:()=>loadDashboard({silent:true}),
    enabled:()=>Boolean(token.value && view.value==='dashboard'),immediate:false});
  function syncDashboardPolling(){polling.sync();}
  watch(token,()=>{serial++;pending=null;dashboard.loading=false;});
  onScopeDispose(()=>{serial++;});
  return {dashboard,loadDashboard,syncDashboardPolling};
}
