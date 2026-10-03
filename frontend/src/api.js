const TOKEN_KEY = 'wfs_csrf_token';

function createError(message, code = 'REQUEST_ERROR') {
  const error = new Error(message);
  error.code = code;
  return error;
}

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || '';
}

export function setToken(token) {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
}

function appendParams(searchParams, params = {}) {
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return;
    }
    if (Array.isArray(value)) {
      value
        .filter((item) => item !== undefined && item !== null && item !== '')
        .forEach((item) => searchParams.append(`${key}[]`, item));
      return;
    }
    searchParams.append(key, value);
  });
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const method = options.method || 'GET';
  const searchParams = new URLSearchParams();
  appendParams(searchParams, options.params);
  const query = searchParams.toString();
  const headers = { ...(options.headers || {}) };
  const token = getToken();

  if (token && !['GET', 'HEAD'].includes(method)) {
    headers['X-CSRF-Token'] = token;
  }

  let body;
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }

  let response;
  let payload;
  const timeout = window.setTimeout(() => controller.abort(), options.timeout || 15000);
  try {
    response = await fetch(query ? `${path}?${query}` : path, {
      method,
      headers,
      body,
      signal: controller.signal,
      credentials: 'same-origin',
    });
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      throw createError('接口返回了页面内容，请确认后端正在运行最新代码。', 'INVALID_JSON_RESPONSE');
    }
    payload = await response.json();
  } catch (error) {
    if (error.code) throw error;
    throw createError(error.name === 'AbortError' ? '请求超时，请稍后重试。' : '无法连接服务，请确认服务已启动。', 'NETWORK_ERROR');
  } finally {
    window.clearTimeout(timeout);
  }

  if (!response.ok && payload.code !== 50008) {
    throw createError(payload.message || `服务请求失败（HTTP ${response.status}）。`, `HTTP_${response.status}`);
  }
  if (payload.code !== 20000) {
    throw createError(payload.message || '请求失败', payload.code);
  }
  return payload.data;
}

export const api = {
  health() {
    return request('/api/user/health');
  },
  login(credentials) {
    return request('/api/user/login', { method: 'POST', body: credentials });
  },
  logout() {
    return request('/api/user/logout', { method: 'POST' });
  },
  userInfo() {
    return request('/api/user/info');
  },
  taskState(params) {
    return request('/api/taskinfo/state', { params });
  },
  dashboard(params = {}) {
    return request('/api/taskinfo/dashboard', { params });
  },
  events() {
    return request('/api/taskinfo/events');
  },
  taskSchedule(params) {
    return request('/api/taskinfo/schedule', { params });
  },
  previewTaskSchedule(payload) {
    return request('/api/taskinfo/schedule', { method: 'POST', body: payload });
  },
  updateTaskSchedule(payload) {
    return request('/api/taskinfo/schedule', { method: 'PUT', body: payload });
  },
  editTask(params) {
    return request('/api/taskinfo/editTask', { method: 'POST', params });
  },
  taskLogs(params) {
    return request('/api/taskinfo/taskLogs', { method: 'POST', params });
  },
  taskLogDetail(params) {
    return request('/api/taskinfo/taskLogDetail', { method: 'POST', params });
  },
  systemLogs(params) {
    return request('/api/taskinfo/systemLogs', { method: 'POST', params });
  },
  taskIds() {
    return request('/api/taskinfo/taskids', { method: 'POST' });
  },
  groups() {
    return request('/api/taskinfo/groups', { method: 'POST' });
  },
  systemIds() {
    return request('/api/taskinfo/systemids', { method: 'POST' });
  },
  reload(params = {}) {
    return request('/api/taskinfo/overloading', { method: 'POST', params });
  },
  updateCode() {
    return request('/api/taskinfo/updatecode', { method: 'POST', timeout: 65000 });
  },
  detailLog(params) {
    return request('/api/taskinfo/logview', { method: 'POST', params });
  },
  callTask(params) {
    return request('/api/taskinfo/call_task', { method: 'POST', params });
  },
  taskDetail(pid) { return request('/api/taskinfo/detail', { params: { pid } }); },
  executionMatrix(params = {}) { return request('/api/taskinfo/matrix', { params, timeout: 30000 }); },
  taskSources(pid, dir = '', offset = 0) { return request('/api/taskinfo/source', { params: { pid, dir, offset } }); },
  taskSource(pid, file) { return request('/api/taskinfo/source', { params: { pid, file } }); },
  runs(pid) { return request('/api/taskinfo/runs', { params: { pid } }); },
  execution(run_id, offset = 0) { return request('/api/taskinfo/run', { params: { run_id, offset } }); },
  restore(payload) { return request('/api/taskinfo/restore', { method: 'POST', body: payload }); },
  users() { return request('/api/admin/users'); },
  saveUser(payload) { return request('/api/admin/users', { method: 'POST', body: payload }); },
  audit() { return request('/api/admin/audit'); },
  runtime() { return request('/api/admin/runtime'); },
  batch(payload) { return request('/api/taskinfo/batch',{method:'POST',body:payload}); },
};
