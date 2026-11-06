<template>
  <ModalShell
    :open="open"
    :label="`任务配置：${task?.name || task?.id || '-'}`"
    panel-class="schedule-modal"
    backdrop-class=""
    @close="requestClose"
  >
    <header class="modal-head">
      <div>
        <h3>任务配置：{{ task?.name || task?.id || '-' }}</h3>
        <p class="modal-subtitle">
          {{ task?.id }} · {{ task?.group_name || '-' }} /
          {{ task?.folder_name || '-' }} · Asia/Shanghai（UTC+8）
        </p>
      </div>
      <button
        class="btn icon-only"
        type="button"
        title="关闭"
        @click="requestClose"
      >
        ×
      </button>
    </header>

    <div class="modal-body schedule-body">
      <LoadingStatus
        :active="loading || saving"
        :label="saving ? '正在保存配置…' : '正在读取配置…'"
      />
      <div v-if="error" class="inline-alert danger">
        <strong>{{ schedule ? '配置保存失败' : '配置加载失败' }}</strong>
        <span>{{ error }}</span>
        <button
          class="btn"
          type="button"
          :disabled="saving || loading"
          @click="$emit('reload')"
          title="重新加载会重置未保存的修改"
        >
          重新加载配置
        </button>
      </div>

      <form
        v-if="schedule"
        class="schedule-form"
        @submit.prevent="submit"
        :aria-busy="loading || saving"
        :inert="loading"
      >
        <div class="schedule-layout">
          <div class="configuration-guide"><strong>配置分工</strong><p>发布：管理代码、默认入口和依赖环境。此页：维护执行时间、名称与资源上限。重试、补跑等在任务详情 → 配置 → 运行策略中管理。</p></div>
          <div class="schedule-overview">
            <div class="runtime-card">
              <label class="toggle-row">
                <input v-model="form.enabled" type="checkbox" />
                <span>
                  <strong>启用自动调度</strong>
                  <small
                    >关闭后任务保持停止状态，但仍可在列表中手动触发。</small
                  >
                </span>
              </label>
              <div class="schedule-grid">
                <div class="form-row">
                  <label for="task-name">任务名称</label>
                  <input
                    id="task-name"
                    v-model.trim="form.task_name"
                    class="input"
                    placeholder="展示名称"
                  />
                </div>
                <div class="form-row">
                  <span class="field-label">当前执行入口</span><code class="entry-summary">{{ form.main_file || '沿用发布入口' }}</code>
                  <details class="entry-override"><summary>高级：覆盖执行入口</summary><p class="hint">通常在代码发布时设置。仅在已发布文件中切换入口；此项不会安装依赖或发布新代码。</p><label for="main-file">入口文件</label>
                  <input
                    id="main-file"
                    v-model.trim="form.main_file"
                    class="input"
                    list="main-file-options"
                    placeholder="main.py"
                  />
                  <datalist id="main-file-options">
                    <option
                      v-for="item in mainFileOptions"
                      :key="item"
                      :value="item"
                    ></option>
                  </datalist></details>
                </div>
                <div class="form-row">
                  <label for="max-instances">同时执行上限</label>
                  <input
                    id="max-instances"
                    v-model.number="form.max_instances"
                    class="input"
                    type="number"
                    min="1"
                  />
                </div>
                <div class="form-row">
                  <label for="timeout-seconds">超时秒数</label>
                  <input
                    id="timeout-seconds"
                    v-model.number="form.timeout_seconds"
                    class="input"
                    type="number"
                    min="0"
                  />
                </div>
              </div>
            </div>

            <section class="runtime-card schedule-metadata">
              <strong>负责人、说明与执行资源</strong>
              <div class="schedule-grid">
                <div class="form-row">
                  <label for="schedule-owner">负责人</label
                  ><input
                    id="schedule-owner"
                    v-model.trim="form.owner"
                    class="input"
                    maxlength="200"
                  />
                </div>
                <div class="form-row">
                  <label for="task-description">任务说明</label
                  ><textarea
                    id="task-description"
                    v-model="form.description"
                    class="input"
                    maxlength="10000"
                    rows="1"
                  ></textarea>
                </div>
                <div class="form-row">
                  <label for="task-memory">内存地址空间上限（MiB）</label
                  ><input
                    id="task-memory"
                    v-model.number="form.memory_mb"
                    class="input"
                    type="number"
                    min="0"
                  />
                </div>
                <div class="form-row">
                  <label for="task-cpu">CPU 时间上限（秒）</label
                  ><input
                    id="task-cpu"
                    v-model.number="form.cpu_seconds"
                    class="input"
                    type="number"
                    min="0"
                  />
                </div>
                <div class="form-row">
                  <label for="task-file">单文件大小上限（MiB）</label
                  ><input
                    id="task-file"
                    v-model.number="form.file_mb"
                    class="input"
                    type="number"
                    min="0"
                  />
                </div>
                <div class="form-row">
                  <label for="task-misfire">调度延迟容忍（秒）</label
                  ><input
                    id="task-misfire"
                    v-model.number="form.misfire_grace_seconds"
                    class="input"
                    type="number"
                    min="1"
                  />
                </div>
              </div>
              <p class="hint">
                资源上限填 0 表示不限，由 Linux
                执行。服务中断后的任务可确认业务数据后手动补跑。
              </p>
            </section>
          </div>
          <section class="schedule-editor" aria-label="调度策略">
            <aside class="schedule-family-list">
              <button
                v-for="family in familyOptions"
                :key="family.id"
                class="schedule-family"
                :class="{ active: form.schedule_family === family.id }"
                type="button"
                @click="selectFamily(family.id)"
              >
                <span>{{ family.icon }}</span>
                <strong>{{ family.label }}</strong>
                <small>{{ family.description }}</small>
              </button>
            </aside>

            <div class="form-row">
              <label for="schedule-type">策略类型</label>
              <select
                id="schedule-type"
                v-model="form.schedule_type"
                class="select"
              >
                <option
                  v-for="option in activeTypeOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </option>
              </select>
            </div>

            <div
              v-if="form.schedule_family === 'interval'"
              class="schedule-grid"
            >
              <div
                v-if="form.schedule_type === 'interval_minutes'"
                class="form-row"
              >
                <label for="interval-minutes">间隔分钟</label>
                <input
                  id="interval-minutes"
                  v-model.number="form.interval_minutes"
                  class="input"
                  type="number"
                  min="1"
                />
              </div>
              <div
                v-if="form.schedule_type === 'interval_hours'"
                class="form-row"
              >
                <label for="interval-hours">间隔小时</label>
                <input
                  id="interval-hours"
                  v-model.number="form.interval_hours"
                  class="input"
                  type="number"
                  min="1"
                />
              </div>
            </div>

            <div
              v-if="
                form.schedule_family === 'fixed' &&
                form.schedule_type !== 'daily_times'
              "
              class="schedule-grid"
            >
              <div v-if="usesFixedTime" class="form-row">
                <label for="fixed-time">执行时间</label>
                <input
                  id="fixed-time"
                  v-model="form.fixed_time"
                  class="input"
                  type="time"
                />
              </div>
              <div
                v-if="form.schedule_type === 'weekly_fixed'"
                class="form-row"
              >
                <label for="weekday">星期</label>
                <select id="weekday" v-model="form.weekday" class="select">
                  <option
                    v-for="option in weekdayOptions"
                    :key="option.value"
                    :value="option.value"
                  >
                    {{ option.label }}
                  </option>
                </select>
              </div>
              <div
                v-if="form.schedule_type === 'monthly_fixed'"
                class="form-row"
              >
                <label for="month-day">每月日期</label>
                <input
                  id="month-day"
                  v-model.number="form.month_day"
                  class="input"
                  type="number"
                  min="1"
                  max="31"
                />
              </div>
              <div
                v-if="form.schedule_type === 'once_at'"
                class="form-row wide"
              >
                <label for="run-datetime">执行时间</label>
                <input
                  id="run-datetime"
                  v-model="form.run_datetime"
                  class="input"
                  type="datetime-local"
                />
              </div>
            </div>

            <div
              v-if="form.schedule_type === 'daily_times'"
              class="daily-times-editor"
            >
              <p class="hint">
                每天按所列时间分别执行（UTC+8），最多 48
                个；重复时间只执行一次。
              </p>
              <div class="daily-times-grid">
                <div
                  v-for="(_, index) in form.daily_times"
                  :key="index"
                  class="daily-time-row"
                >
                  <div class="form-row">
                    <label :for="`daily-time-${index}`"
                      >时间点 {{ index + 1 }}</label
                    >
                    <input
                      :id="`daily-time-${index}`"
                      v-model="form.daily_times[index]"
                      class="input"
                      type="time"
                      step="60"
                      required
                    />
                  </div>
                  <button
                    class="btn"
                    type="button"
                    :aria-label="`删除时间点 ${index + 1}`"
                    :disabled="form.daily_times.length === 1"
                    @click="form.daily_times.splice(index, 1)"
                  >
                    删除
                  </button>
                </div>
              </div>
              <button
                class="btn"
                type="button"
                :disabled="form.daily_times.length >= 48"
                @click="form.daily_times.push('')"
              >
                添加时间点
              </button>
            </div>

            <div v-if="form.schedule_family === 'window'" class="schedule-grid">
              <div class="form-row">
                <label for="window-start">开始时间</label>
                <input
                  id="window-start"
                  v-model="form.window_start"
                  class="input"
                  type="time"
                  step="60"
                />
              </div>
              <div class="form-row">
                <label for="window-end">结束时间</label>
                <input
                  id="window-end"
                  v-model="form.window_end"
                  class="input"
                  type="time"
                  step="60"
                />
              </div>
              <div class="form-row">
                <label for="window-interval">间隔分钟</label>
                <input
                  id="window-interval"
                  v-model.number="form.window_interval_minutes"
                  class="input"
                  type="number"
                  min="1"
                  max="1440"
                />
              </div>
              <div class="form-row">
                <label for="window-weekday">执行日</label>
                <select
                  id="window-weekday"
                  v-model="form.window_day_of_week"
                  class="select"
                >
                  <option value="*">每天</option>
                  <option value="mon-fri">工作日</option>
                  <option
                    v-for="option in weekdayOptions"
                    :key="option.value"
                    :value="option.value"
                  >
                    {{ option.label }}
                  </option>
                </select>
              </div>
            </div>

            <div
              v-if="form.schedule_family === 'advanced'"
              class="schedule-grid cron-grid"
            >
              <div class="form-row">
                <label for="cron-minute">分钟</label>
                <input
                  id="cron-minute"
                  v-model.trim="form.cron_minute"
                  class="input"
                  placeholder="0, */5"
                />
              </div>
              <div class="form-row">
                <label for="cron-hour">小时</label>
                <input
                  id="cron-hour"
                  v-model.trim="form.cron_hour"
                  class="input"
                  placeholder="9, 9-18"
                />
              </div>
              <div class="form-row">
                <label for="cron-day">日期</label>
                <input
                  id="cron-day"
                  v-model.trim="form.cron_day"
                  class="input"
                  placeholder="*, 1, last"
                />
              </div>
              <div class="form-row">
                <label for="cron-month">月份</label>
                <input
                  id="cron-month"
                  v-model.trim="form.cron_month"
                  class="input"
                  placeholder="*"
                />
              </div>
              <div class="form-row">
                <label for="cron-weekday">星期</label>
                <input
                  id="cron-weekday"
                  v-model.trim="form.cron_day_of_week"
                  class="input"
                  placeholder="*, wed, mon-fri"
                />
              </div>
            </div>

            <div class="schedule-preview">
              <div class="preview-head">
                <div>
                  <strong>未来执行时间</strong>
                  <span>{{ previewSourceText }}</span>
                </div>
                <span v-if="previewLoading" class="tag info">计算中</span>
              </div>

              <div
                v-if="displayPreviewError"
                class="inline-alert danger compact-alert"
              >
                <strong>预览失败</strong>
                <span>{{ displayPreviewError }}</span>
              </div>
              <div
                v-else-if="!previewItems.length"
                class="empty-state compact schedule-empty"
              >
                <strong>暂无未来执行点</strong>
                <span>当前策略没有生成可预览的后续时间。</span>
              </div>
              <div v-else class="preview-layout">
                <div class="schedule-calendar">
                  <div
                    v-for="day in calendarDays"
                    :key="day.date"
                    class="calendar-day"
                    :class="{ marked: day.count > 0 }"
                  >
                    <small>{{ day.weekday }}</small>
                    <strong>{{ day.label }}</strong>
                    <span v-if="day.count">{{ day.count }} 次</span>
                  </div>
                </div>
                <div class="preview-timeline">
                  <div
                    v-for="item in previewItems.slice(0, 10)"
                    :key="item.datetime"
                    class="preview-time"
                  >
                    <strong>{{ item.date }}</strong>
                    <span>{{ item.time }}</span>
                  </div>
                </div>
              </div>
            </div>
          </section>
          <section v-if="changes.length" class="schedule-change-review" aria-label="保存前变更摘要"><strong>本次将修改 {{ changes.length }} 项</strong><p class="hint">保存后由调度器应用新配置；请结合上方未来执行时间核对。</p><dl><div v-for="change in changes" :key="change.key"><dt>{{ change.label }}</dt><dd><span class="muted">{{ change.before }}</span><span aria-label="改为"> → </span><strong>{{ change.after }}</strong></dd></div></dl></section>
          <p v-else class="hint">尚未修改配置。</p>
        </div>

        <footer class="confirm-footer schedule-footer">
          <button class="btn" type="button" @click="requestClose">取消</button>
          <button
            class="btn primary"
            type="submit"
            :disabled="saving || loading"
          >
            {{ saving ? '保存中...' : '保存配置' }}
          </button>
        </footer>
      </form>
    </div>
  </ModalShell>
</template>

<script setup>
import ModalShell from './ModalShell.vue';
import { businessDateTime } from '../timebase';
import { computed, onUnmounted, reactive, ref, watch } from 'vue';
import { resetScheduleForm } from '../scheduleForm';
import LoadingStatus from './LoadingStatus.vue';

const props = defineProps({
  open: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  error: { type: String, default: '' },
  preview: { type: Array, default: () => [] },
  previewLoading: { type: Boolean, default: false },
  previewError: { type: String, default: '' },
  task: { type: Object, default: null },
  schedule: { type: Object, default: null },
});

const emit = defineEmits(['close', 'save', 'preview', 'reload']);

const familyOptions = [
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

const typeOptions = {
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

const weekdayOptions = [
  { value: 'mon', label: '周一' },
  { value: 'tue', label: '周二' },
  { value: 'wed', label: '周三' },
  { value: 'thu', label: '周四' },
  { value: 'fri', label: '周五' },
  { value: 'sat', label: '周六' },
  { value: 'sun', label: '周日' },
  { value: 'mon-fri', label: '工作日' },
];

const form = reactive(defaultForm());
let initialForm = '';
const baseline=ref({});
const fieldLabels={enabled:'自动调度',task_name:'任务名称',main_file:'执行入口',max_instances:'同时执行上限',timeout_seconds:'超时（秒）',owner:'负责人',description:'任务说明',memory_mb:'内存（MiB）',cpu_seconds:'CPU 时间（秒）',file_mb:'单文件（MiB）',misfire_grace_seconds:'延迟容忍（秒）',schedule_type:'策略类型',interval_minutes:'间隔（分钟）',interval_hours:'间隔（小时）',fixed_time:'执行时间',daily_times:'每日时间点',weekday:'星期',month_day:'每月日期',window_start:'窗口开始',window_end:'窗口结束',window_interval_minutes:'窗口间隔（分钟）',window_day_of_week:'窗口星期',run_datetime:'单次执行时间',cron_minute:'Cron 分钟',cron_hour:'Cron 小时',cron_day:'Cron 日期',cron_month:'Cron 月份',cron_day_of_week:'Cron 星期'};
function displayChange(key,value){if(key==='enabled')return value?'启用':'暂停';if(key==='schedule_type')return Object.values(typeOptions).flat().find(item=>item.value===value)?.label || value;if(Array.isArray(value))return value.join('、') || '未设置';return value===undefined || value===''?'未填写':String(value);}
const changes=computed(()=>Object.entries(fieldLabels).filter(([key])=>JSON.stringify(form[key])!==JSON.stringify(baseline.value[key])).map(([key,label])=>({key,label,before:displayChange(key,baseline.value[key]),after:displayChange(key,form[key])})));
function requestClose() {
  if (!props.saving)
    emit('close', {
      dirty: Boolean(initialForm) && initialForm !== JSON.stringify(form),
    });
}
let previewTimer = null;

const activeTypeOptions = computed(
  () => typeOptions[form.schedule_family] || typeOptions.interval,
);
const mainFileOptions = computed(() => props.schedule?.main_file_options || []);

const usesFixedTime = computed(() =>
  ['daily_fixed', 'weekly_fixed', 'monthly_fixed', 'monthly_last_day'].includes(
    form.schedule_type,
  ),
);

const previewItems = computed(() => props.preview || []);
const displayPreviewError = computed(() => props.previewError || '');

const previewSourceText = computed(() => {
  const sourceMap = {
    database: '数据库配置',
    unconfigured: '尚未保存',
  };
  const source = sourceMap[props.schedule?.source] || '当前表单';
  return `${source} · ${previewItems.value.length} 个后续时间点`;
});

const calendarDays = computed(() => {
  const byDate = new Map();
  previewItems.value.forEach((item) => {
    byDate.set(item.date, (byDate.get(item.date) || 0) + 1);
  });
  return Array.from(byDate.entries())
    .slice(0, 14)
    .map(([date, count]) => {
      const parsed = new Date(`${date}T00:00:00`);
      return {
        date,
        count,
        label: date.slice(5),
        weekday: parsed.toLocaleDateString('zh-CN', { weekday: 'short' }),
      };
    });
});

watch(
  () => props.schedule,
  (schedule) => {
    resetScheduleForm(form, defaultForm(), schedule?.form || {});
    form.schedule_family = familyForType(form.schedule_type);
    ensureOnceAtDateTime();
    initialForm = JSON.stringify(form);
    baseline.value=JSON.parse(initialForm);
  },
  { immediate: true },
);

watch(
  () => form.schedule_type,
  (scheduleType) => {
    form.schedule_family = familyForType(scheduleType);
    ensureOnceAtDateTime();
  },
);

watch(
  () => JSON.parse(JSON.stringify(form)),
  () => {
    if (!props.open || props.loading) {
      return;
    }
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(() => {
      if (!canPreview()) {
        return;
      }
      emit('preview', JSON.parse(JSON.stringify(form)));
    }, 350);
  },
);

onUnmounted(() => {
  window.clearTimeout(previewTimer);
});

function defaultForm() {
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

function padNumber(value) {
  return String(value).padStart(2, '0');
}

function defaultRunDateTime() {
  return businessDateTime(new Date(Date.now() + 5 * 60 * 1000));
}

function ensureOnceAtDateTime() {
  if (form.schedule_type !== 'once_at') {
    return;
  }
  if (!String(form.run_datetime || '').trim()) {
    form.run_datetime = defaultRunDateTime();
  }
}

function canPreview() {
  if (
    form.schedule_type === 'once_at' &&
    !String(form.run_datetime || '').trim()
  ) {
    return false;
  }
  return true;
}

function familyForType(scheduleType) {
  return (
    familyOptions.find((family) =>
      (typeOptions[family.id] || []).some(
        (option) => option.value === scheduleType,
      ),
    )?.id || 'interval'
  );
}

function selectFamily(familyId) {
  form.schedule_family = familyId;
  if (
    !activeTypeOptions.value.some(
      (option) => option.value === form.schedule_type,
    )
  ) {
    form.schedule_type = activeTypeOptions.value[0]?.value || 'every_minute';
  }
}

function submit() {
  ensureOnceAtDateTime();
  emit('save', JSON.parse(JSON.stringify(form)));
}
</script>

<style scoped>
.configuration-guide,.schedule-change-review{border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;background:var(--panel-soft)}.configuration-guide p{margin:8px 0 0;color:var(--muted);font-size:13px;line-height:1.7}.entry-summary{display:block;padding:10px 12px;min-height:40px;background:var(--panel-soft);border-radius:6px;overflow-wrap:anywhere}.entry-override{margin-top:8px}.entry-override summary{cursor:pointer;color:var(--muted);font-size:13px}.entry-override .hint{line-height:1.6}.schedule-change-review dl{display:grid;gap:8px;margin:12px 0 0}.schedule-change-review dl>div{display:grid;grid-template-columns:150px minmax(0,1fr);gap:12px}.schedule-change-review dd{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}.schedule-change-review dt{color:var(--muted-strong)}.field-label{min-height:20px;line-height:20px;font-weight:600}
@media(max-width:600px){.schedule-change-review dl>div{grid-template-columns:1fr;gap:4px}}
</style>
