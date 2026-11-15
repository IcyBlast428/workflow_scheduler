// One resource, one request at a time. Failed reads back off; writes never retry here.
export function createRefreshLoop({load, canRun = () => true, interval = 5000,
  maxInterval = 60000, onError = () => {}, clock = globalThis}) {
  let timer = null, pending = null, active = false, disposed = false, failures = 0;
  function clear() { if (timer !== null) clock.clearTimeout(timer); timer = null; }
  // 从请求结束后开始计时，而非固定 setInterval，慢请求不会累积成并发轮询。
  function schedule() {
    clear();
    const delay = typeof interval === 'function' ? interval() : interval;
    if (!disposed && active && canRun() && delay > 0)
      timer = clock.setTimeout(() => { timer = null; refresh(); },
        Math.min(maxInterval, delay * 2 ** Math.min(failures, 6)));
  }
  function refresh({manual = false} = {}) {
    if (disposed || (!manual && !canRun())) return Promise.resolve(false);
    if (pending) return pending;
    clear();
    pending = Promise.resolve().then(load).then(result => {
      failures = result === false ? failures + 1 : 0;
      return result;
    }).catch(error => {
      failures++;
      try { onError(error); } catch { /* A reporting failure cannot stop recovery. */ }
      return false;
    }).finally(() => { pending = null; schedule(); });
    return pending;
  }
  return {
    refresh,
    start(immediate = false) { if (disposed) return; active = true; if (immediate) return refresh(); schedule(); },
    sync() { schedule(); },
    stop() { active = false; clear(); },
    // 销毁只撤销后续调度，已经发出的请求仍可能完成；调用方需用序号防止旧结果回写。
    dispose() { disposed = true; active = false; clear(); },
  };
}
