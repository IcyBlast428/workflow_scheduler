import assert from 'node:assert/strict';
import {displayDateTime} from '../src/timebase.js';
assert.equal(displayDateTime('2026-11-05 08:52:29.546499'), '2026-11-05 08:52:29');
assert.equal(displayDateTime('2026-11-05T23:52:29.546499Z'), '2026-11-06 07:52:29');
assert.equal(displayDateTime('2026-11-05T08:52:29-05:00'), '2026-11-05 21:52:29');
assert.equal(displayDateTime(null, '未安排'), '未安排');
assert.equal(displayDateTime('待调度'), '待调度');
console.log('Business timezone and second-precision display passed');
