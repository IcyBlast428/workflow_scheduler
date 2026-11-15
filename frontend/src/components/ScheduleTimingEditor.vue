<template>
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
  <slot />
</section>
</template>
<script setup>
import {computed,toRef} from 'vue';
import {familyOptions,typeOptions,weekdayOptions} from '../scheduleForm.js';
const props=defineProps({form:{type:Object,required:true}});
const form=toRef(props,'form');
const activeTypeOptions=computed(()=>typeOptions[form.value.schedule_family] || typeOptions.interval);
const usesFixedTime=computed(()=>['daily_fixed','weekly_fixed','monthly_fixed','monthly_last_day'].includes(form.value.schedule_type));
function selectFamily(familyId) {
  form.value.schedule_family = familyId;
  if (
    !activeTypeOptions.value.some(
      (option) => option.value === form.value.schedule_type,
    )
  ) {
    form.value.schedule_type = activeTypeOptions.value[0]?.value || 'every_minute';
  }
}


</script>
