import {onMounted, onScopeDispose, watch} from 'vue';
import {createRefreshLoop} from '../refreshLoop.js';
import {subscribeRefreshEnvironment} from '../refreshEnvironment.js';

export function useRefreshLoop({load, enabled = () => true, interval = 5000,
  immediate = true, onError, onResume, key = () => null}) {
  const canRun = () => enabled() && !document.hidden && navigator.onLine !== false;
  const loop = createRefreshLoop({load, interval, onError, canRun});
  const resume = () => {
    if (!canRun()) { loop.sync(); return; }
    onResume?.();
    return loop.start(true);
  };
  watch([enabled, key], ([active]) => { if (active) resume(); else loop.stop(); });
  if (typeof interval === 'function') watch(interval, () => loop.sync());
  let unsubscribe;
  onMounted(() => {
    unsubscribe = subscribeRefreshEnvironment(available => { if (available) resume(); else loop.sync(); });
    if (enabled()) loop.start(immediate);
  });
  onScopeDispose(() => { loop.dispose(); unsubscribe?.(); });
  return loop;
}
