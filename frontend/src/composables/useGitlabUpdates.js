import { computed, onBeforeUnmount, ref, watch } from 'vue';
import {useRefreshLoop} from './useRefreshLoop.js';
import { api } from '../api';

export function useGitlabUpdates(enabled) {
  const summary = ref(null), dismissed = ref('');
  let pending=null, generation = 0;
  function refresh(){if(pending)return pending;pending=fetchSummary().finally(()=>{pending=null;});return pending;}
  async function fetchSummary() {
    if (!enabled.value || document.hidden) return;
    const current = generation;
    try {
      const value = await api.gitlabState(true);
      if (current === generation && enabled.value) summary.value = value;
    } catch {
      // GitLab reminders must not replace the platform's own health status.
      return false;
    }
  }
  function accept(value) {
    if (enabled.value) summary.value = value;
  }
  function dismiss() { dismissed.value = summary.value?.fingerprint || ''; }
  watch(enabled, active => {
    generation += 1;
    summary.value = null;
    dismissed.value = '';
  }, { immediate: true });
  useRefreshLoop({load:refresh,enabled:()=>enabled.value,interval:60000});
  onBeforeUnmount(() => { generation += 1; });
  const showReminder = computed(() => enabled.value && summary.value?.enabled && summary.value?.unread
    && summary.value.count > 0 && summary.value.fingerprint !== dismissed.value);
  return { summary, showReminder, refresh, accept, dismiss };
}
