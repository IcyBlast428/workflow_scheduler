import {onMounted, onScopeDispose, watch} from 'vue';
import {subscribeRefreshEnvironment} from '../refreshEnvironment.js';
import {useRefreshLoop} from './useRefreshLoop.js';

// Polling workspaces own their initial/resume reads. Only non-polling views are
// handled here; explicit user refresh still forces the current view to reload.
export function useWorkspaceRefresh({token, view, loadDashboard, loadTasks, loadGroups,
  loadTaskLogs, loadTaskIds, loadSystemLogs, loadSystemIds, checkBackend, backendStatus, pushToast}) {
  const loadSystem = () => Promise.all([loadSystemLogs(), loadSystemIds()]);
  useRefreshLoop({load: loadSystem, enabled: () => Boolean(token.value && view.value === 'systemLogs'), interval: 0});
  watch([token, view], ([authenticated, currentView]) => {
    if (authenticated && currentView === 'tasks') loadGroups();
  }, {immediate: true});
  let unsubscribe, pending;
  onMounted(() => {
    unsubscribe = subscribeRefreshEnvironment(available => {
      if (available && token.value && view.value === 'packages')
        window.dispatchEvent(new Event('wfs:packages-refresh'));
    });
  });
  onScopeDispose(() => unsubscribe?.());

  function refreshActiveView(options = {}) {
    if (pending) return pending;
    pending = refresh(options).finally(() => { pending = null; });
    return pending;
  }
  async function refresh(options) {
    const silent = options.silent === true;
    const target = view.value, identity = token.value;
    if (!identity) return;
    const reachable = await checkBackend({silent: true});
    // A late health response must not refresh a different page or another user.
    if (target !== view.value || identity !== token.value) return;
    if (!reachable) {
      if (!silent) pushToast('error', '刷新失败', backendStatus.error);
      return;
    }
    if (target === 'dashboard') return loadDashboard({silent});
    if (target === 'tasks') return Promise.all([loadTasks(false, {silent}), ...(silent ? [] : [loadGroups()])]);
    if (target === 'taskLogs') return Promise.all([loadTaskLogs(false, {silent, buffer: silent}), ...(silent ? [] : [loadTaskIds()])]);
    if (['matrix', 'queue'].includes(target)) window.dispatchEvent(new CustomEvent('wfs:matrix-refresh', {detail: {silent}}));
    else if (target === 'packages') window.dispatchEvent(new Event('wfs:packages-refresh'));
    else if (target === 'systemLogs') return loadSystem();
  }
  return {refreshActiveView};
}
