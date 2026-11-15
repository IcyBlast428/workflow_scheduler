// A page has one visibility/network lifecycle, shared by all resource readers.
export function createRefreshEnvironment({documentTarget, windowTarget, online}) {
  const subscribers = new Set();
  const isAvailable = () => !documentTarget.hidden && documentTarget.visibilityState !== 'hidden' && online();
  let available = isAvailable();
  function changed() {
    const next = isAvailable();
    if (next === available) return;
    available = next;
    for (const subscriber of [...subscribers]) subscriber(available);
  }
  function listen(method) {
    documentTarget[method]('visibilitychange', changed);
    windowTarget[method]('online', changed);
    windowTarget[method]('offline', changed);
  }
  return {
    subscribe(callback) {
      if (!subscribers.size) { available = isAvailable(); listen('addEventListener'); }
      subscribers.add(callback);
      return () => { if (!subscribers.delete(callback)) return; if (!subscribers.size) listen('removeEventListener'); };
    },
  };
}
let environment;
export function subscribeRefreshEnvironment(callback) {
  environment ??= createRefreshEnvironment({documentTarget: document, windowTarget: window,
    online: () => navigator.onLine !== false});
  return environment.subscribe(callback);
}
