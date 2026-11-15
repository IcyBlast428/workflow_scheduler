<template>
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
</template>
<script setup>
import {computed} from 'vue';
defineOptions({name:'SchedulePreview'});
const props=defineProps({preview:{type:Array,default:()=>[]},previewLoading:Boolean,previewError:{type:String,default:''},source:{type:String,default:''}});
const previewItems = computed(() => props.preview || []);
const displayPreviewError = computed(() => props.previewError || '');

const previewSourceText = computed(() => {
  const sourceMap = {
    database: '数据库配置',
    unconfigured: '尚未保存',
  };
  const source = sourceMap[props.source] || '当前表单';
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

</script>
