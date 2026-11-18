export const logColumnLabels = {
  id: '任务 ID',
  group: '组名',
  folder: '任务目录',
  status: '状态',
  duration: '耗时',
  start: '开始时间',
  end: '结束时间',
};

export const logColumnOptions = Object.entries(logColumnLabels).map(([key, label]) => ({ key, label }));
export const defaultDesktopLogColumns = Object.keys(logColumnLabels);
export const defaultMobileLogColumns = ['status', 'end'];
