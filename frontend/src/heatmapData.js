const abnormal = new Set(['failed','timed_out','interrupted','skipped','missed','unknown']);
export function heatmapRows(data, limit = 50) {
  const cells = new Map();
  for (const record of [...data.records,...data.active]) {
    const time = record.time || record.start_time || data.server_time;
    const hour = Number(time.slice(11,13)); if (!Number.isInteger(hour) || hour < 0 || hour > 23) continue;
    const key = `${record.pid}:${hour}`;
    let cell = cells.get(key);
    if (!cell) { cell = {count:0,status:'success',record:null}; cells.set(key,cell); }
    cell.count += record.count || 1;
    const status = abnormal.has(record.status) ? 'failed' : ['running','queued'].includes(record.status) ? 'running' : record.status === 'cancelled' ? 'cancelled' : 'success';
    const rank = {success:0,cancelled:1,running:2,failed:3};
    if (!cell.record || rank[status] > rank[cell.status] || (rank[status] === rank[cell.status] && time > (cell.record.time || cell.record.start_time || ''))) { cell.record = record; cell.status = status; }
  }
  return data.tasks.slice(0,limit).map(task => ({task,cells:Array.from({length:24},(_,hour) => cells.get(`${task.pid}:${hour}`) || null)}));
}
