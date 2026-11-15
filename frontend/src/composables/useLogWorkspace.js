import { api } from '../api.js';
import { reactive, ref, onScopeDispose } from 'vue';
import { recentDates } from '../timebase.js';
export function recentLogDates() {
  return recentDates();
}
export function useLogWorkspace({
  markBackendHealthy,
  handleRequestFailure,
  syncRoute,
}) {
  let taskLogRequestSerial = 0,
    systemLogRequestSerial = 0;
  // 输入框中的条件可能还未提交；后台检测只复用已应用查询，不能偷跑未确认的筛选。
  let appliedTaskQuery=null;
  const matrixLogRange = ref([]);
  onScopeDispose(() => {
    taskLogRequestSerial++;
    systemLogRequestSerial++;
  });
  const dates = recentLogDates();
  const taskLogs = reactive({
    cursors: [''],
    nextCursor: '',
    hasMore: false,
    loading: false,
    loaded: false,
    error: '',
    rows: [],
    total: 0,
    ids: [],
    newRecords:false,
    refreshError:'',
    params: {
      scope: 'online',
      taskid: '',
      taskname: '',
      taskstate: '',
      startDate: dates.start,
      endDate: dates.end,
      currentPage: 1,
      pagesize: 10,
    },
  });
  const systemLogs = reactive({
    hasMore: false,
    loading: false,
    error: '',
    rows: [],
    total: 0,
    ids: [],
    params: {
      systemids: '',
      startDate: '',
      endDate: '',
      currentPage: 1,
      pagesize: 10,
    },
  });
  function buildDateRange(params) {
    if (params.startDate && params.endDate) {
      return [params.startDate, params.endDate];
    }
    return [];
  }

  function taskLogQueryParams() {
    return {
      scope: taskLogs.params.scope,
      cursor: taskLogs.cursors[taskLogs.params.currentPage - 1] || '',
      taskid: taskLogs.params.taskid,
      taskname: taskLogs.params.taskname,
      taskstate: taskLogs.params.taskstate,
      datetimeval: matrixLogRange.value.length
        ? matrixLogRange.value
        : buildDateRange(taskLogs.params),
      currentPage: taskLogs.params.currentPage,
      pagesize: taskLogs.params.pagesize,
    };
  }
  function hasCurrentTaskLogQuery() {
    return taskLogs.loaded && !taskLogs.loading && !taskLogs.error && JSON.stringify(appliedTaskQuery) === JSON.stringify(taskLogQueryParams());
  }
  function clearTaskLogFilter(key) {
    if (key === 'range') matrixLogRange.value = [];
    else if (key === 'scope') taskLogs.params.scope = 'online';
    else if (key === 'dates') {
      const dates = recentLogDates();
      taskLogs.params.startDate = dates.start;
      taskLogs.params.endDate = dates.end;
    } else if (['taskid','taskname','taskstate'].includes(key)) taskLogs.params[key] = '';
    else return;
    syncRoute();
    loadTaskLogs(true);
  }

  // 自动更新只提示有新记录，保留用户正在查看的行和分页，避免新任务挤走点击目标。
  // 手动刷新/搜索才替换列表；查看后续页时仅设置提示，不重新查询第一页覆盖当前页。
  async function loadTaskLogs(resetPage = false, options = {}) {
    const buffering=options.buffer===true;
    if(buffering && (!taskLogs.loaded || taskLogs.newRecords || taskLogs.loading)) return;
    if(buffering && taskLogs.params.currentPage!==1){taskLogs.newRecords=true;return;}
    if (resetPage) {
      taskLogs.params.currentPage = 1;
      taskLogs.cursors = [''];
    }
    const serial = ++taskLogRequestSerial;
    const query=buffering && appliedTaskQuery ? {...appliedTaskQuery} : taskLogQueryParams();
    if(!buffering){appliedTaskQuery={...query};taskLogs.newRecords=false;}
    if (!options.silent) {
      taskLogs.loading = true;
    }
    if(!options.silent)taskLogs.error = '';
    try {
      const data = await api.taskLogs(query);
      // 同时保护结果、错误和 loading 状态；只判断成功分支会让旧请求清掉新请求的状态。
      if (serial !== taskLogRequestSerial) return;
      markBackendHealthy('后端连接正常');
      taskLogs.refreshError='';
      if(buffering && taskLogs.rows.length){
        const identity=row=>`${row.logid || row.id}@${row.datetime}`;
        const known=new Set(taskLogs.rows.map(identity));
        if((data.data || []).some(row=>!known.has(identity(row)))) taskLogs.newRecords=true;
        return;
      }
      taskLogs.rows = data.data || [];
      taskLogs.loaded=true;
      taskLogs.total = data.total || 0;
      taskLogs.hasMore = Boolean(data.has_more);
      taskLogs.nextCursor = data.next_cursor || '';
    } catch (error) {
      if (serial !== taskLogRequestSerial) return;
      if(options.silent){taskLogs.refreshError='后台更新暂不可用，将自动重试。';return;}
      await handleRequestFailure(error, { state: taskLogs });
    } finally {
      if (!options.silent && serial === taskLogRequestSerial) {
        taskLogs.loading = false;
      }
    }
  }

  async function loadTaskIds() {
    try {
      taskLogs.ids = await api.taskIds();
      markBackendHealthy('后端连接正常');
    } catch (error) {
      await handleRequestFailure(error, { toastTitle: '任务 ID 加载失败' });
    }
  }

  function resetTaskLogFilters() {
    matrixLogRange.value = [];
    const dates = recentLogDates();
    taskLogs.params.scope = 'online';
    taskLogs.params.taskid = '';
    taskLogs.params.taskname = '';
    taskLogs.params.taskstate = '';
    taskLogs.params.startDate = dates.start;
    taskLogs.params.endDate = dates.end;
    syncRoute();
    loadTaskLogs(true);
  }

  function setLogRange(days) {
    const dates = recentDates(days);
    taskLogs.params.startDate = dates.start;
    taskLogs.params.endDate = dates.end;
    searchTaskLogs();
  }

  function searchTaskLogs() {
    matrixLogRange.value = [];
    syncRoute();
    loadTaskLogs(true);
  }

  // 翻页使用后端游标而非重新计算偏移量；改变筛选或每页条数时必须重置游标链。
  function setTaskLogPage(page) {
    if (taskLogs.loading) return;
    if (page > taskLogs.params.currentPage) {
      if (!taskLogs.nextCursor) return;
      taskLogs.cursors[page - 1] = taskLogs.nextCursor;
    }
    taskLogs.params.currentPage = page;
    loadTaskLogs();
  }

  function setTaskLogPageSize(size) {
    taskLogs.params.pagesize = size;
    taskLogs.params.currentPage = 1;
    loadTaskLogs(true);
  }

  function systemLogQueryParams() {
    return {
      systemids: systemLogs.params.systemids,
      datetimeval: buildDateRange(systemLogs.params),
      currentPage: systemLogs.params.currentPage,
      pagesize: systemLogs.params.pagesize,
    };
  }

  async function loadSystemLogs(resetPage = false) {
    const serial = ++systemLogRequestSerial;
    if (resetPage) {
      systemLogs.params.currentPage = 1;
    }
    systemLogs.loading = true;
    systemLogs.error = '';
    try {
      const data = await api.systemLogs(systemLogQueryParams());
      if (serial !== systemLogRequestSerial) return;
      markBackendHealthy('后端连接正常');
      systemLogs.rows = data.data || [];
      systemLogs.total = data.total || 0;
      systemLogs.hasMore = Boolean(data.has_more);
    } catch (error) {
      if (serial !== systemLogRequestSerial) return;
      await handleRequestFailure(error, { state: systemLogs });
    } finally {
      if (serial === systemLogRequestSerial) systemLogs.loading = false;
    }
  }

  async function loadSystemIds() {
    try {
      systemLogs.ids = await api.systemIds();
      markBackendHealthy('后端连接正常');
    } catch (error) {
      await handleRequestFailure(error, { toastTitle: '平台事件 ID 加载失败' });
    }
  }

  function resetSystemLogFilters() {
    systemLogs.params.systemids = '';
    systemLogs.params.startDate = '';
    systemLogs.params.endDate = '';
    loadSystemLogs(true);
  }

  function setSystemLogPage(page) {
    systemLogs.params.currentPage = page;
    loadSystemLogs();
  }

  function setSystemLogPageSize(size) {
    systemLogs.params.pagesize = size;
    systemLogs.params.currentPage = 1;
    loadSystemLogs();
  }
  return {
    taskLogs,
    hasCurrentTaskLogQuery,
    clearTaskLogFilter,
    systemLogs,
    matrixLogRange,
    loadTaskLogs,
    loadTaskIds,
    resetTaskLogFilters,
    setLogRange,
    searchTaskLogs,
    setTaskLogPage,
    setTaskLogPageSize,
    loadSystemLogs,
    loadSystemIds,
    resetSystemLogFilters,
    setSystemLogPage,
    setSystemLogPageSize,
  };
}
