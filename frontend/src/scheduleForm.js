// A reused dialog must keep only editable fields belonging to the current task.
export function resetScheduleForm(target, defaults, source = {}) {
  for (const key of Object.keys(target)) delete target[key];
  for (const key of Object.keys(defaults)) {
    const value = Object.hasOwn(source, key) ? source[key] : defaults[key];
    target[key] = Array.isArray(value) ? [...value] : value;
  }
}

export function scheduleRequest(pid, form) {
  // Task identity comes from the dialog owner, never from saved JSON or form fields.
  return { ...form, pid };
}

export const familyOptions = [
  {
    id: 'interval',
    icon: 'I',
    label: '周期间隔',
    description: '按分钟或小时循环',
  },
  {
    id: 'fixed',
    icon: 'F',
    label: '固定时间',
    description: '按日、周、月指定时间',
  },
  {
    id: 'window',
    icon: 'W',
    label: '时间窗口',
    description: '在区间内循环执行',
  },
  {
    id: 'advanced',
    icon: '#',
    label: '高级规则',
    description: '自定义 Cron 表达式',
  },
];

export const typeOptions = {
  interval: [
    { value: 'every_minute', label: '每分钟执行' },
    { value: 'every_hour', label: '每小时执行' },
    { value: 'interval_minutes', label: '每 N 分钟执行' },
    { value: 'interval_hours', label: '每 N 小时执行' },
  ],
  fixed: [
    { value: 'daily_fixed', label: '每天固定时间执行' },
    { value: 'daily_times', label: '每天多个时间点' },
    { value: 'weekly_fixed', label: '每周固定时间执行' },
    { value: 'monthly_fixed', label: '每月固定日期固定时间执行' },
    { value: 'monthly_last_day', label: '每月最后一天固定时间执行' },
    { value: 'once_at', label: '单次指定时间执行' },
  ],
  window: [{ value: 'window_minutes', label: '区间时间内按分钟执行' }],
  advanced: [{ value: 'custom_cron', label: '自定义 Cron' }],
};

export const weekdayOptions = [
  { value: 'mon', label: '周一' },
  { value: 'tue', label: '周二' },
  { value: 'wed', label: '周三' },
  { value: 'thu', label: '周四' },
  { value: 'fri', label: '周五' },
  { value: 'sat', label: '周六' },
  { value: 'sun', label: '周日' },
  { value: 'mon-fri', label: '工作日' },
];

export function defaultScheduleForm() {
  return {
    enabled: false,
    task_name: '',
    main_file: 'main.py',
    max_instances: 1,
    timeout_seconds: 0,
    version: 0,
    owner: '',
    description: '',
    memory_mb: 0,
    cpu_seconds: 0,
    file_mb: 100,
    misfire_grace_seconds: 600,
    schedule_family: 'interval',
    schedule_type: 'every_minute',
    interval_minutes: 1,
    interval_hours: 1,
    fixed_time: '09:00',
    daily_times: ['09:00'],
    weekday: 'wed',
    month_day: 1,
    window_start: '09:30',
    window_end: '18:15',
    window_interval_minutes: 1,
    window_day_of_week: '*',
    run_datetime: '',
    cron_minute: '0',
    cron_hour: '9',
    cron_day: '*',
    cron_month: '*',
    cron_day_of_week: '*',
  };
}

export function familyForType(scheduleType) {
  return (
    familyOptions.find((family) =>
      (typeOptions[family.id] || []).some(
        (option) => option.value === scheduleType,
      ),
    )?.id || 'interval'
  );
}
