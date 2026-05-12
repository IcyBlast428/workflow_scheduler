const TOKEN_KEY = 'wfs_admin_token';

function createError(message, code = 'REQUEST_ERROR') {
  const error = new Error(message);
  error.code = code;
  return error;
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
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
  const method = options.method || 'GET';
  const searchParams = new URLSearchParams();
  appendParams(searchParams, options.params);
  const query = searchParams.toString();
  const headers = { ...(options.headers || {}) };
  const token = getToken();

  if (token) {
    headers['X-Token'] = token;
  }

  let body;
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }

  let response;
  try {
    response = await fetch(query ? `${path}?${query}` : path, {
      method,
      headers,
      body,
    });
  } catch (error) {
    throw createError('无法连接后端服务，请确认 127.0.0.1:8008 已启动。', 'NETWORK_ERROR');
  }

  if (!response.ok) {
    throw createError(`服务请求失败（HTTP ${response.status}）。`, `HTTP_${response.status}`);
  }

  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    throw createError('接口返回了页面内容，请确认 Flask 后端正在运行最新代码。', 'INVALID_JSON_RESPONSE');
  }

  const payload = await response.json();
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
  dashboard() {
    return request('/api/taskinfo/dashboard');
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
    return request('/api/taskinfo/updatecode', { method: 'POST' });
  },
  detailLog(params) {
    return request('/api/taskinfo/logview', { method: 'POST', params });
  },
  callTask(params) {
    return request('/api/taskinfo/call_task', { params });
  },
};
