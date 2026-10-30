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
  if (options.formData !== undefined) {
    body = options.formData;
  } else if (options.body !== undefined) {
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

  if (!response.ok && payload.code !== 50008 && !(options.acceptUnavailable && response.status === 503)) {
    throw createError(payload.message || `服务请求失败（HTTP ${response.status}）。`, `HTTP_${response.status}`);
  }
  if (payload.code !== 20000) {
    throw createError(payload.message || '请求失败', payload.code);
  }
  return payload.data;
}

export const api = {
  dispatchStatus(params={}) { return request('/api/admin/operational/dispatch',{params}); },
  operationalPolicy(kind,pid='') { return request(`/api/admin/operational/policy/${kind}`,{params:{pid}}); },
  saveOperationalPolicy(kind,body,pid='') { return request(`/api/admin/operational/policy/${kind}`,{method:'POST',params:{pid},body}); },
  cancelExecutionRequest(id) {return request('/api/admin/operational/requests',{method:'POST',body:{action:'cancel',id}});},
  executionRequests(pid='') { return request('/api/admin/operational/requests',{params:{pid}}); },
  async submitExecutionRequest(pid,body) {
    const storageKey='wfs:execution-request:'+getToken()+':'+pid+':'+JSON.stringify({kind:body.kind,context:body.context || {}});
    let identifier=sessionStorage.getItem(storageKey);
    if(!identifier){identifier=body.request_id || crypto.randomUUID().replaceAll('-','');sessionStorage.setItem(storageKey,identifier);}
    try {
      const result=await request('/api/admin/operational/requests',{method:'POST',params:{pid},body:{...body,request_id:identifier}});
      sessionStorage.removeItem(storageKey);return result;
    } catch(error) {
      if(['HTTP_400','HTTP_401','HTTP_403','HTTP_404','HTTP_413'].includes(error.code))sessionStorage.removeItem(storageKey);
      throw error;
    }
  },
  connectionUsage() { return request('/api/admin/operational/connections'); },
  connectionLifecycle(body) { return request('/api/admin/operational/connection',{method:'POST',body}); },
  notificationQueue() { return request('/api/admin/operational/notifications'); },
  resolveNotification(body) { return request('/api/admin/operational/notifications',{method:'POST',body}); },
  cleanupPlan(keep) { return request('/api/admin/operational/cleanup',{params:{keep},timeout:20000}); },
  cleanupVersions(body) { return request('/api/admin/operational/cleanup',{method:'POST',body,timeout:65000}); },
  resolveIssue(body) { return request('/api/admin/operational/issue',{method:'POST',body}); },
  backupStatus() { return request('/api/admin/operational/backup'); },
  isolationProbe() { return request('/api/admin/operational/isolation-probe',{method:'POST',body:{},timeout:20000}); },
  taskAccess(username) { return request('/api/admin/task-access',{params:{username}}); },
  saveTaskAccess(username,body) { return request('/api/admin/task-access',{method:'POST',params:{username},body}); },
  admission() { return request('/api/admin/admission'); },
  setAdmission(body) { return request('/api/admin/admission', {method:'POST',body}); },
  taskConnections(pid) { return request('/api/admin/task-connections', {params:{pid}}); },
  saveTaskConnections(pid,body) { return request('/api/admin/task-connections', {method:'POST',params:{pid},body}); },
  gitlabConfiguration() { return request('/api/admin/gitlab-updates/configuration'); },
  saveGitlabConfiguration(body) { return request('/api/admin/gitlab-updates/configuration', { method: 'POST', body }); },
  gitlabState(brief = false) { return request('/api/admin/gitlab-updates/state', { params: { brief } }); },
  scanGitlab() { return request('/api/admin/gitlab-updates/scan', { method: 'POST', body: {} }); },
  acknowledgeGitlab(fingerprint) { return request('/api/admin/gitlab-updates/acknowledge', { method: 'POST', body: { fingerprint } }); },
  gitlabDiff(id, index) { return request('/api/admin/gitlab-updates/diff', { params: { id, index } }); },
  taskExamples() { return request('/api/admin/task-publishing/examples'); },
  saveTaskExample(body) { return request('/api/admin/task-publishing/examples', {method:'POST', body}); },
  packageRepository() { return request('/api/admin/task-publishing/repository'); },
  savePackageRepository(body) { return request('/api/admin/task-publishing/repository', {method:'POST', body}); },
  databaseConnections() { return request('/api/admin/database-connections'); },
  changeDatabaseConnection(action, body) { return request(`/api/admin/database-connections/${action}`, {method: 'POST', body, timeout: 65000}); },
  attention() { return request('/api/taskinfo/attention'); },
  storage(keep) { return request('/api/admin/storage', {params:{keep},timeout:20000}); },
  packages(pid = '') { return request('/api/taskinfo/packages', { params: { pid } }); },
  packagePreview(pid, version, path) { return request('/api/taskinfo/packages/preview', { params: { pid, version, path } }); },
  gitlabTasks() { return request('/api/taskinfo/packages/gitlab'); },
  gitlabTaskAction(body) { return request('/api/taskinfo/packages/gitlab', { method: 'POST', body, timeout: 65000 }); },
  packageAction(body) { return request('/api/taskinfo/packages/action', { method: 'POST', body, timeout: 65000 }); },
  health() {
    return request('/api/user/health');
  },
  readiness() {
    return request('/api/user/ready', { acceptUnavailable: true });
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
  detailLog(params) {
    return request('/api/taskinfo/logview', { method: 'POST', params });
  },
  discardManualRequest(pid) { sessionStorage.removeItem('wfs:manual:' + getToken() + ':' + pid); },
  async callTask(params) {
    const storageKey = 'wfs:manual:' + getToken() + ':' + params.pid;
    let requestId = sessionStorage.getItem(storageKey);
    if (!requestId) { requestId = crypto.randomUUID().replaceAll('-', ''); sessionStorage.setItem(storageKey, requestId); }
    try {
      const data = await request('/api/taskinfo/call_task', { method: 'POST', params, body: { request_id: requestId } });
      sessionStorage.removeItem(storageKey); return data;
    } catch (error) {
      throw error;
    }
  },
  taskDetail(pid) { return request('/api/taskinfo/detail', { params: { pid } }); },
  taskFlow(pid) { return request('/api/taskinfo/flow', { params: { pid }, timeout: 30000 }); },
  executionMatrix(params = {}) { return request('/api/taskinfo/matrix', { params, timeout: 30000 }); },
  taskSources(pid, dir = '', offset = 0) { return request('/api/taskinfo/source', { params: { pid, dir, offset } }); },
  taskSource(pid, file) { return request('/api/taskinfo/source', { params: { pid, file } }); },
  runs(pid) { return request('/api/taskinfo/runs', { params: { pid } }); },
  execution(run_id, offset = 0) { return request('/api/taskinfo/run', { params: { run_id, offset } }); },
  artifacts(run_id, dir = '', offset = 0) { return request('/api/taskinfo/artifacts', {params:{run_id,dir,offset}}); },
  artifactPreview(run_id, file) { return request('/api/taskinfo/artifacts', {params:{run_id,file}}); },
  restore(payload) { return request('/api/taskinfo/restore', { method: 'POST', body: payload }); },
  users() { return request('/api/admin/users'); },
  saveUser(payload) { return request('/api/admin/users', { method: 'POST', body: payload }); },
  audit() { return request('/api/admin/audit'); },
  runtime() { return request('/api/admin/runtime'); },
  batch(payload) { return request('/api/taskinfo/batch',{method:'POST',body:payload}); },
};
