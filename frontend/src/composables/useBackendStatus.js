import { reactive, onScopeDispose } from 'vue';
import { api } from '../api';

export function useBackendStatus() {
  const backendStatus = reactive({
    checking: false,
    reachable: false,
    ready: false,
    error: '',
    message: '正在连接后端…',
    checkedAt: '',
    components: {},
  });
  let pending,
    stopped = false;
  function markBackendHealthy() {
    backendStatus.reachable = true;
    backendStatus.error = '';
    backendStatus.checkedAt = new Date().toLocaleTimeString('zh-CN', {
      hour12: false,
    });
  }
  async function probe() {
    backendStatus.checking = true;
    try {
      await api.health();
      if (stopped) return false;
      markBackendHealthy();
      try {
        const state = await api.readiness();
        if (stopped) return false;
        backendStatus.ready = state.ready;
        backendStatus.components = state.components || {};
        backendStatus.message = state.ready
          ? '接口、数据库与调度状态已检查'
          : Object.values(state.components || {})
              .filter((item) => item.status === 'unavailable')
              .map((item) => item.message)
              .join('；') || '服务尚未就绪';
      } catch {
        if (stopped) return false;
        backendStatus.ready = false;
        backendStatus.components = {};
        backendStatus.message = '接口已连接，暂时无法检查数据库与调度状态';
      }
      return true;
    } catch (error) {
      if (!stopped)
        Object.assign(backendStatus, {
          reachable: false,
          ready: false,
          components: {},
          error: error.message,
          message: error.message,
        });
      return false;
    } finally {
      if (!stopped) backendStatus.checking = false;
    }
  }
  function checkBackend() {
    if (!pending)
      pending = probe().finally(() => {
        pending = null;
      });
    return pending;
  }
  const timer = window.setInterval(() => {
    if (!document.hidden) checkBackend();
  }, 30000);
  onScopeDispose(() => {
    stopped = true;
    window.clearInterval(timer);
  });
  return { backendStatus, markBackendHealthy, checkBackend };
}
