export function readPreference(key, fallback) {
  try { const value = JSON.parse(localStorage.getItem(key) || 'null'); return value ?? fallback; }
  catch { return fallback; }
}
export function writePreference(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Storage is optional. */ }
}
export function mergeMatrixSnapshot(previous, incoming) {
  if (!incoming.incremental || !previous || incoming.date !== previous.date) return incoming;
  const records = new Map(previous.records.map(row => [row.key, row]));
  for (const key of incoming.removed || []) records.delete(key);
  for (const row of incoming.records) records.set(row.key, row);
  return { ...incoming, records: [...records.values()] };
}
export function matrixQuery(live, date, cursor = '') { return { ...(live ? {} : { date }), cursor }; }
