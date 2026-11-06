// One resource, one request at a time. Failed reads back off; writes never retry here.
export function createRefreshLoop({load, canRun = () => true, interval = 5000,
  maxInterval = 60000, onError = () => {}, clock = globalThis}) {
  let timer = null, pending = null, active = false, disposed = false, failures = 0;
  function clear() { if (timer !== null) clock.clearTimeout(timer); timer = null; }
  function schedule() {
    clear();
    if (!disposed && active && canRun())
      timer = clock.setTimeout(() => { timer = null; refresh(); },
        Math.min(maxInterval, interval * 2 ** Math.min(failures, 6)));
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
    dispose() { disposed = true; active = false; clear(); },
  };
}
