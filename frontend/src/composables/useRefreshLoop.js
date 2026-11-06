import {onMounted, onScopeDispose, watch} from 'vue';
import {createRefreshLoop} from '../refreshLoop.js';

export function useRefreshLoop({load, enabled = () => true, interval = 5000,
  immediate = true, onError}) {
  const loop = createRefreshLoop({load, interval, onError,
    canRun: () => enabled() && !document.hidden && navigator.onLine !== false});
  const resume = () => { loop.sync(); if (enabled()) loop.refresh(); };
  watch(enabled, active => { loop.sync(); if (active) loop.refresh(); });
  onMounted(() => {
    loop.start(immediate);
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('online', resume);
    window.addEventListener('offline', loop.sync);
  });
  onScopeDispose(() => {
    loop.dispose();
    document.removeEventListener('visibilitychange', resume);
    window.removeEventListener('online', resume);
    window.removeEventListener('offline', loop.sync);
  });
  return loop;
}
