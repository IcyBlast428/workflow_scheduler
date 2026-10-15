import { reactive, watch, onScopeDispose } from 'vue';
import { api } from '../api.js';
import { timestamp } from '../timebase.js';
export function useDashboardWorkspace({
  token,
  view,
  markBackendHealthy,
  handleRequestFailure,
}) {
  let dashboardPollTimer = null,
    dashboardPollInFlight = false,
    serial = 0;
  const DASHBOARD_POLL_MS = 5000;
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
  async function loadDashboard(options = {}) {
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
    } catch (error) {
      if (current !== serial) return;
      await handleRequestFailure(error, {
        state: dashboard,
        toastTitle: options.silent ? '' : '总览加载失败',
      });
    } finally {
      if (current === serial && !options.silent) {
        dashboard.loading = false;
      }
    }
  }

  function shouldPollDashboard() {
    return Boolean(
      token.value &&
        view.value === 'dashboard' &&
        document.visibilityState !== 'hidden',
    );
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
        dashboardPollTimer = window.setInterval(
          pollDashboard,
          DASHBOARD_POLL_MS,
        );
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
  watch(
    () => Boolean(token.value && view.value === 'dashboard'),
    syncDashboardPolling,
  );
  onScopeDispose(() => {
    serial++;
    stopDashboardPolling();
  });
  return { dashboard, loadDashboard, syncDashboardPolling };
}
