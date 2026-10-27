import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { api } from '../api';

export function useGitlabUpdates(enabled) {
  const summary = ref(null), dismissed = ref('');
  let timer, generation = 0;
  async function refresh() {
    if (!enabled.value || document.hidden) return;
    const current = generation;
    try {
      const value = await api.gitlabState(true);
      if (current === generation && enabled.value) summary.value = value;
    } catch {
      // GitLab reminders must not replace the platform's own health status.
    }
  }
  function accept(value) {
    if (enabled.value) summary.value = value;
  }
  function dismiss() { dismissed.value = summary.value?.fingerprint || ''; }
  watch(enabled, active => {
    generation += 1;
    clearInterval(timer);
    summary.value = null;
    dismissed.value = '';
    if (active) {
      refresh();
      timer = setInterval(refresh, 60000);
    }
  }, { immediate: true });
  function visible() { if (!document.hidden) refresh(); }
  document.addEventListener('visibilitychange', visible);
  onBeforeUnmount(() => { clearInterval(timer); generation += 1; document.removeEventListener('visibilitychange', visible); });
  const showReminder = computed(() => enabled.value && summary.value?.enabled && summary.value?.unread
    && summary.value.count > 0 && summary.value.fingerprint !== dismissed.value);
  return { summary, showReminder, refresh, accept, dismiss };
}
