import assert from 'node:assert/strict';
import {createRefreshLoop} from '../src/refreshLoop.js';
const timers=new Map();let id=0,enabled=true,calls=0,resolve;
const clock={setTimeout(fn,delay){timers.set(++id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);}};
const flush=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
const loop=createRefreshLoop({clock,interval:100,canRun:()=>enabled,load:()=>{calls++;return new Promise(done=>{resolve=done;});}});
const initial=loop.start(true);await flush();assert.equal(calls,1);
assert.equal(loop.refresh(),initial,'Simultaneous reads share the same promise');
resolve(false);await initial;assert.equal([...timers.values()][0].delay,200);
enabled=false;loop.sync();assert.equal(timers.size,0);await loop.refresh();assert.equal(calls,1,'Paused resources do not load');
enabled=true;const recovered=loop.refresh();await flush();resolve(true);await recovered;assert.equal([...timers.values()][0].delay,100,'Success restores the normal cadence');
const next=loop.refresh();await flush();loop.dispose();resolve(true);await next;assert.equal(timers.size,0,'An in-flight completion must not rearm a disposed timer');
await loop.refresh({manual:true});assert.equal(calls,3);
let failures=0;
const failing=createRefreshLoop({clock,interval:100,maxInterval:800,load:()=>{throw Error('offline');},onError:()=>{failures++;}});
for(let i=0;i<8;i++){await failing.start(true);assert.ok([...timers.values()][0].delay<=800);}
assert.equal(failures,8);assert.equal([...timers.values()][0].delay,800);failing.stop();assert.equal(timers.size,0);failing.dispose();
console.log('Refresh loop deduplication, pause, recovery, bounded backoff and disposal passed.');
