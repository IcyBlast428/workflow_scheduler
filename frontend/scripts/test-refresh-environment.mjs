import assert from 'node:assert/strict';
import {createRefreshEnvironment} from '../src/refreshEnvironment.js';
import {createRefreshLoop} from '../src/refreshLoop.js';
class Target extends EventTarget {
  handlers = new Map();
  addEventListener(type, fn) { super.addEventListener(type, fn); this.handlers.set(type, (this.handlers.get(type) || 0) + 1); }
  removeEventListener(type, fn) { super.removeEventListener(type, fn); this.handlers.set(type, (this.handlers.get(type) || 0) - 1); }
}
const page = new Target(), windowTarget = new Target();
page.hidden = false; page.visibilityState = 'visible'; let online = true;
const environment = createRefreshEnvironment({documentTarget: page, windowTarget, online: () => online});
const received = [[], []];
const off = received.map(events => environment.subscribe(available => events.push(available)));
assert.equal(page.handlers.get('visibilitychange'), 1, 'One browser listener serves all resources');
assert.equal(windowTarget.handlers.get('online'), 1);
page.hidden = true; page.visibilityState = 'hidden'; page.dispatchEvent(new Event('visibilitychange'));
online = false; windowTarget.dispatchEvent(new Event('offline'));
page.hidden = false; page.visibilityState = 'visible'; page.dispatchEvent(new Event('visibilitychange'));
assert.deepEqual(received, [[false], [false]], 'Becoming visible while offline does not resume');
online = true; windowTarget.dispatchEvent(new Event('online'));
windowTarget.dispatchEvent(new Event('online')); page.dispatchEvent(new Event('visibilitychange'));
assert.deepEqual(received, [[false, true], [false, true]], 'Visibility/online notifications share a single resume');
off[0](); assert.equal(page.handlers.get('visibilitychange'), 1);
off[1](); assert.equal(page.handlers.get('visibilitychange'), 0); assert.equal(windowTarget.handlers.get('online'), 0);

let cadence = 10000, calls = 0, handle = 0, allowed = true, finish;
const timers = new Map(), clock = {setTimeout(fn, delay) {timers.set(++handle, {fn, delay}); return handle;}, clearTimeout(id) {timers.delete(id);}};
const loop = createRefreshLoop({clock, interval: () => cadence, canRun: () => allowed,
  load: () => {calls++; return new Promise(resolve => { finish = resolve; });}});
const flush = async () => {for (let i = 0; i < 12; i++) await Promise.resolve();};
const first = loop.start(true); await flush(); finish(true); await first;
assert.equal(calls, 1); assert.equal([...timers.values()][0].delay, 10000);
cadence = 0; loop.sync(); assert.equal(timers.size, 0, 'Historical mode cancels the previous live timer');
allowed = false; loop.sync(); await loop.refresh(); assert.equal(calls, 1);
allowed = true; const resumed = loop.refresh(); await flush(); finish(true); await resumed;
assert.equal(calls, 2); assert.equal(timers.size, 0, 'Historical mode resumes once without starting polling');
cadence = 10000; loop.sync(); assert.equal(timers.size, 1);
const next = [...timers.values()][0]; timers.clear(); next.fn(); await flush();
const repeated = loop.refresh(); assert.equal(calls, 3, 'Resume/manual requests share an in-flight periodic read');
finish(true); await repeated; assert.equal(timers.size, 1);
loop.dispose(); assert.equal(timers.size, 0);
console.log('Shared visibility/network resume, teardown, request deduplication and historical/live cadence passed.');
