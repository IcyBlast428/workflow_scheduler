export const statusLabels = {
  queued: '排队中', running: '执行中', success: '成功', failed: '脚本失败',
  timed_out: '超时或资源终止', cancelled: '已取消', interrupted: '重启中断', skipped: '并发已满，跳过', missed:'错过调度窗口', unknown:'未知',pending:'待执行',
};
export function statusLabel(status) { return statusLabels[status] || status || '未知'; }
export function statusClass(status) {
  if (['success', '成功'].includes(status)) return 'success';
  if (['failed', 'timed_out', '失败', '脚本失败', '超时/终止', statusLabels.timed_out].includes(status)) return 'danger';
  if (['running', 'queued', statusLabels.running, statusLabels.queued].includes(status)) return 'brand';
  return 'info';
}
export function exitClass(state) {
  if (state === null || state === undefined || state === '') return 'info';
  const value = Number(state);
  return value === 0 ? 'success' : [-15, -1, -10001, -10002].includes(value) || Number.isNaN(value) ? 'info' : 'danger';
}
export function exitLabel(state) {
  if (state === null || state === undefined || state === '') return '暂无';
  return ({ 0: '成功', '-9': '超时或资源终止', '-15': '已取消', '-1': '重启中断', '-10001':'并发跳过','-10002':'错过调度' })[state] || `失败（${state}）`;
}
export function canTrigger(row) {
  return row.state !== 'invalid' && (row.running_instances || 0) < (row.max_instances || 1);
}
export function actionLabel(action) {
  const packages = {package_upload:'上传任务包',package_import:'导入任务版本',package_prepare:'检查任务依赖',package_publish:'发布任务版本',package_rollback:'回滚任务代码',package_trash:'任务移入回收站',package_restore:'恢复任务'};
  if (packages[action]) return packages[action];
  return ({login:'登录',logout:'退出','/api/taskinfo/editTask':'任务启停或刷新','/api/taskinfo/call_task':'手动执行','/api/taskinfo/schedule':'修改调度配置','/api/taskinfo/restore':'恢复配置','/api/taskinfo/overloading':'同步或重载任务','/api/taskinfo/updatecode':'检查版本','/api/admin/users':'维护账户'})[action] || action;
}
