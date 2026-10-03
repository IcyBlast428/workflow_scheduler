import assert from 'node:assert/strict';
import { resetScheduleForm, scheduleRequest } from '../src/scheduleForm.js';

const defaults={ version:0, enabled:false, task_name:'', main_file:'main.py', interval_minutes:1 };
const form={};
resetScheduleForm(form,defaults,{pid:'first',updated_by:'previous',version:7,task_name:'first task',interval_minutes:8});
assert.equal(form.version,7);
assert.equal('pid' in form,false);
// Reproduce the old stale-field condition, then open another unconfigured task.
form.pid='first';form.updated_by='previous';form.unrelated='old';
resetScheduleForm(form,defaults,{version:0,main_file:'second.py'});
assert.deepEqual(form,{...defaults,main_file:'second.py'});
form.enabled=true;form.interval_minutes=3;
assert.equal(scheduleRequest('second',{...form,pid:'first'}).pid,'second');
assert.equal(scheduleRequest('second',form).version,0);
resetScheduleForm(form,defaults,{version:9,enabled:true,interval_minutes:5});
assert.equal(scheduleRequest('second',form).version,9,'Existing versions must remain intact for conflict checks');
console.log('Cross-task form reset, request identity and configuration version regression passed.');
