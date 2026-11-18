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
  const initialState = () => ({
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
    failure_rank: [],
    cpu_timeline: {
      samples: [],
      markers: [],
      current: null,
      current_memory: null,
      sample_interval_seconds: 5,
      retention_hours: 6,
      warning: '',
    },
  });
  const dashboard = reactive(initialState());
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
    dashboard.error = '';
    try {
      const data = await api.dashboard(
        options.silent ? { after: dashboard.cpu_timeline.cursor || '' } : {},
      );
      if (current !== serial) return;
      dashboard.loaded = true;
      markBackendHealthy('后端连接正常');
      Object.assign(dashboard.summary, data.summary || {});
      dashboard.failure_rank = data.failure_rank || [];
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

  useRefreshLoop({load:()=>loadDashboard({silent:dashboard.loaded}),
    enabled:()=>Boolean(token.value && view.value==='dashboard'),immediate:false});
  watch(token,()=>{serial++;pending=null;Object.assign(dashboard,initialState());});
  onScopeDispose(()=>{serial++;});
  return {dashboard,loadDashboard};
}
