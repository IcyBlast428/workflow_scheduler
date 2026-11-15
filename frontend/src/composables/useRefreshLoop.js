import {onMounted, onScopeDispose, watch} from 'vue';
import {createRefreshLoop} from '../refreshLoop.js';
import {subscribeRefreshEnvironment} from '../refreshEnvironment.js';

// 把读请求的轮询绑定到组件、可见性和联网状态；隐藏页不持续请求，恢复时立即补读。
export function useRefreshLoop({load, enabled = () => true, interval = 5000,
  immediate = true, onError, onResume, key = () => null}) {
  const canRun = () => enabled() && !document.hidden && navigator.onLine !== false;
  const loop = createRefreshLoop({load, interval, onError, canRun});
  const resume = () => {
    if (!canRun()) { loop.sync(); return; }
    onResume?.();
    return loop.start(true);
  };
  // key 通常包含账号或筛选上下文，变化后即使页面未切换也必须重新读取。
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
