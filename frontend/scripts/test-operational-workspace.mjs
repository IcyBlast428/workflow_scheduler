import assert from 'node:assert/strict';
import { businessDate, businessDateTime, recentDates, timestamp } from '../src/timebase.js';
import { readRoute, routeHash } from '../src/routeLocation.js';
import { heatmapRows } from '../src/heatmapData.js';
for (const timezone of ['UTC','America/New_York','Asia/Shanghai']) {
  process.env.TZ=timezone;
  assert.equal(businessDate(new Date('2026-10-04T18:00:00Z')),'2026-10-05');
  assert.equal(businessDateTime(new Date('2026-10-04T18:03:00Z')),'2026-10-05T02:03');
  assert.deepEqual(recentDates(7,new Date('2026-10-04T18:00:00Z')),{start:'2026-09-29',end:'2026-10-05'});
  assert.equal(timestamp('2026-10-05 02:03:00'),Date.parse('2026-10-04T18:03:00Z'));
}
const hash=routeHash('taskLogs',{pid:'group__one',taskname:'日报 & 汇总',start:'2026-10-04'});
assert.equal(readRoute(hash).params.get('taskname'),'日报 & 汇总');
assert.equal(readRoute(hash).pid,'group__one');
assert.equal(readRoute('#unknown?pid=../../etc').pid,'');
assert.equal(readRoute('#tasks?run=invalid').run,'');
const data={server_time:'2026-10-04 10:20:00',tasks:[{pid:'one',name:'one'}],active:[],records:[
  {pid:'one',time:'2026-10-04 10:00:00',status:'failed',count:2},
  {pid:'one',time:'2026-10-04 10:30:00',status:'success',count:3}]};
const cell=heatmapRows(data)[0].cells[10];assert.equal(cell.count,5);assert.equal(cell.status,'failed');assert.equal(cell.record.status,'failed');
assert.equal(heatmapRows({...data,records:[]})[0].cells[10],null);
console.log('Timezone-independent dates, deep links and heatmap anomaly precedence passed.');
