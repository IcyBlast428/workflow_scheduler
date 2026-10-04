const views = new Set(['dashboard','tasks','taskLogs','systemLogs','matrix','packages','admin']);
export function readRoute(hash) {
  const [raw, query = ''] = hash.replace(/^#/, '').split('?');
  const params = new URLSearchParams(query);
  const pid = params.get('pid') || '', run = params.get('run') || '';
  return { view: views.has(raw) ? raw : 'dashboard', params,
    pid: pid.length <= 200 && !/[\x00-\x1f/\\]/.test(pid) ? pid : '',
    run: /^[a-f0-9]{32}$/.test(run) ? run : '' };
}
export function routeHash(view, values = {}) {
  const params = new URLSearchParams();
  for (const [key,value] of Object.entries(values)) if (value !== '' && value != null) params.set(key,String(value));
  return `#${views.has(view) ? view : 'dashboard'}${params.size ? '?'+params : ''}`;
}
