import assert from 'node:assert/strict';
import {readFile,writeFile,unlink} from 'node:fs/promises';
import {effectScope,ref,reactive} from 'vue';
const files=['api','logs','live'].map(name=>new URL(`.log-updates-${process.pid}-${name}.mjs`,import.meta.url));
const [mock,logModule,liveModule]=files;
const scope=effectScope(),timers=new Map();let id=0;
globalThis.setTimeout=fn=>{timers.set(++id,fn);return id;};globalThis.clearTimeout=id=>timers.delete(id);
globalThis.window={addEventListener(){},removeEventListener(){}};
globalThis.document={visibilityState:'visible',hidden:false,addEventListener(){},removeEventListener(){}};
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
try{
 await writeFile(mock,`export const logs=[],events=[];export const api={taskLogs:params=>new Promise((resolve,reject)=>logs.push({params,resolve,reject})),events:()=>new Promise(resolve=>events.push({resolve}))};`);
 await writeFile(logModule,(await readFile(new URL('../src/composables/useLogWorkspace.js',import.meta.url),'utf8')).replace("'../api.js'",JSON.stringify(mock.href)).replace("'../timebase.js'",JSON.stringify(new URL('../src/timebase.js',import.meta.url).href)));
 await writeFile(liveModule,(await readFile(new URL('../src/composables/useLiveUpdates.js',import.meta.url),'utf8')).replace("'../api.js'",JSON.stringify(mock.href)).replace("'./useLogWorkspace.js'",JSON.stringify(logModule.href)).replace("'./useRefreshLoop.js'",JSON.stringify(new URL('../src/composables/useRefreshLoop.js',import.meta.url).href)));
 const {logs,events}=await import(mock.href),{useLogWorkspace}=await import(logModule.href),{useLiveUpdates}=await import(liveModule.href);
 const options={markBackendHealthy(){},handleRequestFailure(){},syncRoute(){}};
 const workspace=scope.run(()=>useLogWorkspace(options));
 const live=scope.run(()=>useLiveUpdates({...options,token:ref('token'),view:ref('taskLogs'),tasks:reactive({items:[]}),taskLogs:workspace.taskLogs,loadTasks:async()=>{},loadTaskLogs:workspace.loadTaskLogs}));
 const row=id=>({logid:id,id:'task',datetime:id});
 const result=rows=>({data:rows,total:rows.length,next_cursor:'next',has_more:true});
 live.startLiveEvents();await flush();
 events[0].resolve({logs:{revision:1},tasks:[]});await flush();
 assert.equal(logs.length,0,'A marker before initial loading must not populate rows ahead of the foreground request');
 const initial=workspace.loadTaskLogs();
 assert.equal(logs.length,1,'A live marker during initial loading must not replace its request');
 logs[0].resolve(result([row('old')]));await initial;
 const tick=[...timers.values()][0],next=tick();await flush();
 events[1].resolve({logs:{revision:1},tasks:[]});await next;await flush();
 assert.equal(logs.length,2,'An unchanged marker is retried after initial loading; it must not be lost');
 logs[1].resolve(result([row('new'),row('old')]));await flush();
 assert.deepEqual(workspace.taskLogs.rows.map(row=>row.logid),['old']);
 assert.equal(workspace.taskLogs.newRecords,true);
 assert.equal(workspace.taskLogs.loading,false);
 const apply=workspace.loadTaskLogs(true);logs[2].resolve(result([row('new'),row('old')]));await apply;
 assert.equal(workspace.taskLogs.newRecords,false);assert.equal(workspace.taskLogs.rows[0].logid,'new');
 workspace.taskLogs.draft.taskname='未提交的筛选';
 assert.equal(workspace.taskLogs.hasDraft,true);
 const background=workspace.loadTaskLogs(false,{silent:true,buffer:true});
 assert.equal(logs[3].params.taskname,'','Background reads must retain the applied search');
 logs[3].reject(new Error('temporary'));await background;
 assert.equal(workspace.taskLogs.error,'');assert.ok(workspace.taskLogs.refreshError);assert.equal(workspace.taskLogs.rows[0].logid,'new');
 const pageTwo=workspace.setTaskLogPage(2);
 assert.equal(logs[4].params.taskname,'','Pagination must keep the applied filters');
 assert.equal(logs[4].params.cursor,'next','The previous page cursor stays bound to its original query');
 logs[4].resolve(result([row('page-two')]));await pageTwo;
 const subsequent=tick();await flush();events[2].resolve({logs:{revision:2},tasks:[]});await subsequent;await flush();
 assert.equal(logs.length,5,'New results on page two must not trigger a replacement history query');
 assert.equal(workspace.taskLogs.newRecords,true);assert.equal(workspace.taskLogs.rows[0].logid,'page-two');
 assert.equal(workspace.taskLogs.params.currentPage,2);

 const update=workspace.loadTaskLogs(true);
 assert.equal(logs[5].params.taskname,'','Explicitly refreshing new records must preserve applied filters');
 assert.equal(logs[5].params.cursor,'');
 logs[5].resolve(result([row('newest')]));await update;

 const search=workspace.searchTaskLogs();
 assert.equal(logs[6].params.taskname,'未提交的筛选');
 assert.equal(logs[6].params.cursor,'');
 assert.equal(workspace.taskLogs.rows.length,0,'An in-flight query must not present old rows under new chips');
 assert.equal(workspace.taskLogs.hasDraft,false);
 logs[6].resolve(result([]));await search;

 workspace.taskLogs.draft.taskstate='失败';
 const sameRoute=new URLSearchParams({taskname:'未提交的筛选'});
 await workspace.applyTaskLogRoute(sameRoute);
 assert.equal(logs.length,7,'Opening a detail on the same query must not reload the list');
 assert.equal(workspace.taskLogs.draft.taskstate,'失败','Details must not discard an unrelated draft');

 const archive=new URLSearchParams({scope:'archive',start:'2026-11-12',end:'2026-11-18'});
 const applyArchive=workspace.applyTaskLogRoute(archive);
 assert.equal(workspace.taskLogs.hasDraft,false,'A changed route restores the corresponding form');
 assert.equal(logs[7].params.scope,'archive');
 logs[7].resolve(result([]));await applyArchive;
 assert.equal(workspace.taskLogs.canExpandDates,true);

 const expand=workspace.expandTaskLogDates();
 assert.equal(logs[8].params.scope,'archive');
 assert.deepEqual(logs[8].params.datetimeval,['2026-08-18','2026-11-18']);
 assert.equal(workspace.taskLogs.canExpandDates,false);
 logs[8].resolve(result([]));await expand;

 console.log('Execution logs keep drafts separate from displayed filters, pagination, refreshes and archive recovery.');
}finally{scope.stop();await Promise.all(files.map(file=>unlink(file).catch(()=>{})));}
