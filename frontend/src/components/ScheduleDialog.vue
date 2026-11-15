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
          <ScheduleTaskSettings :form="form" :main-file-options="schedule.main_file_options || []" />
          <ScheduleTimingEditor :form="form">
            <SchedulePreview :preview="preview" :preview-loading="previewLoading" :preview-error="previewError" :source="schedule.source" />
          </ScheduleTimingEditor>
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
import {resetScheduleForm,defaultScheduleForm as defaultForm,typeOptions,familyForType} from '../scheduleForm.js';
import ScheduleTaskSettings from './ScheduleTaskSettings.vue';
import ScheduleTimingEditor from './ScheduleTimingEditor.vue';
import SchedulePreview from './SchedulePreview.vue';
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

function submit() {
  ensureOnceAtDateTime();
  emit('save', JSON.parse(JSON.stringify(form)));
}
</script>

<style scoped>
.configuration-guide,.schedule-change-review{border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;background:var(--panel-soft)}.configuration-guide p{margin:8px 0 0;color:var(--muted);font-size:13px;line-height:1.7}.schedule-change-review dl{display:grid;gap:8px;margin:12px 0 0}.schedule-change-review dl>div{display:grid;grid-template-columns:150px minmax(0,1fr);gap:12px}.schedule-change-review dd{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}.schedule-change-review dt{color:var(--muted-strong)}
@media(max-width:600px){.schedule-change-review dl>div{grid-template-columns:1fr;gap:4px}}
</style>
