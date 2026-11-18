import { api } from '../api.js';
import { reactive, ref, onScopeDispose } from 'vue';
import { recentDates } from '../timebase.js';
export function recentLogDates() {
  return recentDates();
}

const filterRouteKeys = {
  taskid: 'taskid',
  taskname: 'taskname',
  taskstate: 'state',
  startDate: 'start',
  endDate: 'end',
  scope: 'scope',
};

function defaultTaskLogFilters() {
  const dates = recentLogDates();
  return {
    scope: 'online',
    taskid: '',
    taskname: '',
    taskstate: '',
    startDate: dates.start,
    endDate: dates.end,
  };
}

export function useLogWorkspace({
  markBackendHealthy,
  handleRequestFailure,
  syncRoute,
}) {
  let taskLogRequestSerial = 0,
    systemLogRequestSerial = 0;
  let requestedTaskQuery = null;
  const matrixLogRange = ref([]);
  onScopeDispose(() => {
    taskLogRequestSerial++;
    systemLogRequestSerial++;
  });
  const defaultFilters = defaultTaskLogFilters();
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
    draft: { ...defaultFilters },
    get hasDraft() {
      return Object.keys(this.draft).some(key => this.draft[key] !== this.params[key]);
    },
    get canExpandDates() {
      return Boolean(expandedStartDate());
    },
    params: {
      ...defaultFilters,
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
    return (taskLogs.loaded || taskLogs.loading) && !taskLogs.error &&
      JSON.stringify(requestedTaskQuery) === JSON.stringify(taskLogQueryParams());
  }

  function updateTaskLogFilters(filters) {
    Object.assign(taskLogs.params, filters);
    Object.assign(taskLogs.draft, filters);
  }

  function applyTaskLogRoute(params) {
    const defaults = defaultTaskLogFilters();
    const filters = Object.fromEntries(Object.entries(filterRouteKeys).map(([key, param]) => [
      key, (params.get(param) ?? defaults[key]).slice(0, 200),
    ]));
    if (!['online', 'archive', 'all'].includes(filters.scope)) filters.scope = 'online';
    const range = [params.get('from'), params.get('to')];
    const preciseRange = range.every(value =>
      value && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d{1,6})?$/.test(value),
    ) ? range : [];
    if (Object.keys(filters).some(key => filters[key] !== taskLogs.params[key]) ||
        preciseRange.join() !== matrixLogRange.value.join()) {
      updateTaskLogFilters(filters);
      matrixLogRange.value = preciseRange;
    }
    if (!hasCurrentTaskLogQuery()) return loadTaskLogs(true);
  }

  function clearTaskLogFilter(key) {
    if (key === 'range') matrixLogRange.value = [];
    else if (key === 'scope') updateTaskLogFilters({ scope: 'online' });
    else if (key === 'dates') {
      const dates = recentLogDates();
      updateTaskLogFilters({ startDate: dates.start, endDate: dates.end });
    } else if (['taskid', 'taskname', 'taskstate'].includes(key)) updateTaskLogFilters({ [key]: '' });
    else return;
    return applyTaskLogFilters();
  }

  // 自动更新只提示有新记录，保留用户正在查看的行和分页，避免新任务挤走点击目标。
  // 手动刷新/搜索才替换列表；查看后续页时仅设置提示，不重新查询第一页覆盖当前页。
  async function loadTaskLogs(resetPage = false, options = {}) {
    const buffering=options.buffer===true;
    if(buffering && (!taskLogs.loaded || taskLogs.newRecords || taskLogs.loading)) return;
    if (options.silent && taskLogs.loading) return;
    if(buffering && taskLogs.params.currentPage!==1){taskLogs.newRecords=true;return;}
    if (resetPage) {
      taskLogs.params.currentPage = 1;
      taskLogs.cursors = [''];
    }
    const serial = ++taskLogRequestSerial;
    const query = taskLogQueryParams();
    if (!buffering) {
      // 不让变更后的筛选标签显示在上一次查询的结果上。
      if (resetPage && JSON.stringify(query) !== JSON.stringify(requestedTaskQuery)) {
        taskLogs.rows = [];
        taskLogs.loaded = false;
        taskLogs.total = 0;
        taskLogs.hasMore = false;
        taskLogs.nextCursor = '';
      }
      requestedTaskQuery = query;
      taskLogs.newRecords = false;
    }
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
    updateTaskLogFilters(defaultTaskLogFilters());
    return applyTaskLogFilters();
  }

  function setLogRange(days) {
    const dates = recentDates(days);
    matrixLogRange.value = [];
    updateTaskLogFilters({ startDate: dates.start, endDate: dates.end });
    return applyTaskLogFilters();
  }

  function expandedStartDate() {
    const { startDate, endDate } = taskLogs.params;
    if (matrixLogRange.value.length || !startDate || !endDate) return '';
    const end = new Date(`${endDate}T00:00:00+08:00`);
    if (Number.isNaN(end.getTime())) return '';
    const start = recentDates(93, end).start;
    return start < startDate ? start : '';
  }

  function expandTaskLogDates() {
    const startDate = expandedStartDate();
    if (!startDate) return;
    updateTaskLogFilters({ startDate });
    return applyTaskLogFilters();
  }

  function searchTaskLogs() {
    matrixLogRange.value = [];
    updateTaskLogFilters(taskLogs.draft);
    return applyTaskLogFilters();
  }

  function applyTaskLogFilters() {
    syncRoute();
    return loadTaskLogs(true);
  }

  // 翻页使用后端游标而非重新计算偏移量；改变筛选或每页条数时必须重置游标链。
  function setTaskLogPage(page) {
    if (taskLogs.loading) return;
    if (page > taskLogs.params.currentPage) {
      if (!taskLogs.nextCursor) return;
      taskLogs.cursors[page - 1] = taskLogs.nextCursor;
    }
    taskLogs.params.currentPage = page;
    return loadTaskLogs();
  }

  function setTaskLogPageSize(size) {
    if (taskLogs.loading) return;
    taskLogs.params.pagesize = size;
    taskLogs.params.currentPage = 1;
    return loadTaskLogs(true);
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
    applyTaskLogRoute,
    expandTaskLogDates,
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
