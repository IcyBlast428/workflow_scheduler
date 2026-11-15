<template>
  <div
    ref="chartRoot"
    class="cpu-timeline"
    :class="{ dragging }"
    @wheel="handleWheel"
    @mousedown="handleMouseDown"
    @mousemove="handleMouseMove"
    @mouseleave="handleMouseLeave"
    @auxclick.prevent
  >
    <svg
      class="cpu-svg"
      :style="{ height: `${chartHeight}px` }"
      :viewBox="`0 0 ${chartWidth} ${chartHeight}`"
      role="img"
      aria-label="CPU timeline"
    >
      <rect class="cpu-plot-bg" :x="margin.left" :y="plotTop" :width="plotWidth" :height="plotHeight" rx="8" />

      <g class="cpu-grid">
        <g v-for="tick in yTicks" :key="tick">
          <line :x1="margin.left" :x2="plotRight" :y1="yForCpu(tick)" :y2="yForCpu(tick)" />
          <text :x="margin.left - 10" :y="yForCpu(tick) + 4" text-anchor="end">{{ tick }}%</text>
        </g>
        <g v-for="tick in xTicks" :key="tick.time">
          <line :x1="xForTime(tick.time)" :x2="xForTime(tick.time)" :y1="plotTop" :y2="plotBottom" />
          <text :x="xForTime(tick.time)" :y="chartHeight - 18" text-anchor="middle">{{ tick.label }}</text>
        </g>
      </g>

      <path v-if="areaPath" class="cpu-area" :d="areaPath" />
      <path v-if="linePath" class="cpu-line" :d="linePath" />
      <path v-if="memoryLinePath" class="memory-line" :d="memoryLinePath" />

      <g class="task-tracks">
        <line
          v-for="lane in taskLaneIndexes"
          :key="lane"
          :x1="margin.left"
          :x2="plotRight"
          :y1="laneCenterY(lane)"
          :y2="laneCenterY(lane)"
        />
        <g
          v-for="block in taskBlocks"
          :key="block.key"
          class="task-block-group"
          @mouseenter="showTaskTooltip(block, $event)"
          @mousemove="showTaskTooltip(block, $event)"
          @mouseleave="clearTooltip"
        >
          <clipPath :id="block.clipId">
            <rect :x="block.x" :y="block.y" :width="block.width" :height="taskBarHeight" rx="5" />
          </clipPath>
          <rect
            class="task-block"
            :class="{ running: block.running, failed: block.failed }"
            :x="block.x"
            :y="block.y"
            :width="block.width"
            :height="taskBarHeight"
            rx="5"
            :style="{ fill: block.color }"
          />
          <text
            v-if="block.width >= 56"
            class="task-block-label"
            :x="block.x + 7"
            :y="block.y + 15"
            :clip-path="`url(#${block.clipId})`"
          >
            {{ block.label }}
          </text>
          <title>{{ taskTitle(block) }}</title>
        </g>
      </g>

      <g v-if="hoverSample" class="cpu-hover">
        <line :x1="xForTime(hoverSample.time)" :x2="xForTime(hoverSample.time)" :y1="plotTop" :y2="plotBottom" />
        <circle :cx="xForTime(hoverSample.time)" :cy="yForCpu(hoverSample.cpu)" r="4" />
        <circle
          v-if="Number.isFinite(hoverSample.memory)"
          class="memory-dot"
          :cx="xForTime(hoverSample.time)"
          :cy="yForCpu(hoverSample.memory)"
          r="4"
        />
      </g>
    </svg>

    <div v-if="tooltip.open" class="cpu-tooltip" :style="tooltipStyle">
      <strong>{{ tooltip.title }}</strong>
      <span v-for="line in tooltip.lines" :key="line">{{ line }}</span>
    </div>

    <div v-if="!normalizedSamples.length" class="cpu-empty">
      <strong>等待 CPU 采样</strong>
    </div>
  </div>
</template>

<script setup>
import {normalizeSamples,normalizeTasks,timelineRange,layoutTaskLanes,MAX_TASK_LANES,formatFullTime,formatTick,formatDuration,hashText,taskColor} from '../cpuTimelineData.js';
import {useCpuTimelineViewport} from '../composables/useCpuTimelineViewport.js';
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';

const props = defineProps({
  samples: { type: Array, default: () => [] },
  markers: { type: Array, default: () => [] },
  retentionHours: { type: Number, default: 6 },
});

const MIN_CHART_HEIGHT = 300;
const TASK_LANE_HEIGHT = 24;
const TASK_BAR_HEIGHT = 18;
const TASK_AREA_PADDING = 10;
const MIN_TASK_BLOCK_WIDTH = 4;
const chartRoot = ref(null);
const chartWidth = ref(900);
const chartHeight = ref(640);
const margin = { top: 22, left: 56, right: 24, bottom: 48 };
const hoverSample = ref(null);
const tooltip = reactive({
  open: false,
  title: '',
  lines: [],
  x: 0,
  y: 0,
});
let resizeObserver = null;

const plotRight = computed(() => chartWidth.value - margin.right);
const plotWidth = computed(() => Math.max(1, chartWidth.value - margin.left - margin.right));
const taskBarHeight = TASK_BAR_HEIGHT;

const normalizedSamples = computed(() => normalizeSamples(props.samples));
const normalizedTasks = computed(() => normalizeTasks(props.markers));
const fullRange = computed(() => timelineRange(normalizedSamples.value, normalizedTasks.value, props.retentionHours));
const {viewStart,viewEnd,dragging,xForTime,timeForX,pointX,pointY,handleWheel,handleMouseDown} = useCpuTimelineViewport({
  chartRoot, fullRange, plotLeft:margin.left, plotRight, plotWidth,
  hasData:computed(() => Boolean(normalizedSamples.value.length || normalizedTasks.value.length)),
});

const visibleSamples = computed(() => normalizedSamples.value.filter((item) => (
  item.time >= viewStart.value && item.time <= viewEnd.value
)));

const lineSamples = computed(() => visibleSamples.value.slice());

const visibleTasks = computed(() => normalizedTasks.value.filter((item) => (
  item.end >= viewStart.value && item.start <= viewEnd.value
)));

const laidOutTasks = computed(() => layoutTaskLanes(visibleTasks.value, viewEnd.value-viewStart.value, plotWidth.value));

const taskLaneCount = computed(() => {
  if (!laidOutTasks.value.length) {
    return 0;
  }
  return Math.min(MAX_TASK_LANES, Math.max(...laidOutTasks.value.map((item) => item.lane)) + 1);
});

const plotTop = computed(() => margin.top);
const plotHeight = computed(() => Math.max(180, chartHeight.value - margin.top - margin.bottom));
const plotBottom = computed(() => plotTop.value + plotHeight.value);
const taskLaneIndexes = computed(() => Array.from({ length: taskLaneCount.value }, (_, index) => index));

const taskBlocks = computed(() => laidOutTasks.value.map((task, index) => {
  const startX = xForTime(Math.max(task.start, viewStart.value));
  const endX = xForTime(Math.min(task.end, viewEnd.value));
  const x = Math.max(margin.left, Math.min(startX, plotRight.value - MIN_TASK_BLOCK_WIDTH));
  const width = Math.max(MIN_TASK_BLOCK_WIDTH, Math.min(plotRight.value - x, endX - x));
  return {
    ...task,
    key: `${task.id || task.index}-${task.start}-${index}`,
    clipId: `task-clip-${index}-${Math.abs(hashText(`${task.id || ''}${task.start}`))}`,
    x,
    y: laneY(task.lane),
    width,
    color: taskColor(task),
  };
}));

const yTicks = Array.from({ length: 11 }, (_, index) => 100 - index * 10);

const xTicks = computed(() => {
  const span = Math.max(1, viewEnd.value - viewStart.value);
  const count = chartWidth.value < 640 ? 4 : 6;
  return Array.from({ length: count }, (_, index) => {
    const time = viewStart.value + (span * index) / (count - 1);
    return {
      time,
      label: formatTick(time, span),
    };
  });
});

const linePath = computed(() => {
  if (!lineSamples.value.length) {
    return '';
  }
  return lineSamples.value
    .map((item, index) => `${index === 0 ? 'M' : 'L'} ${xForTime(item.time).toFixed(1)} ${yForCpu(item.cpu).toFixed(1)}`)
    .join(' ');
});

const memoryLinePath = computed(() => {
  const samples = lineSamples.value.filter((item) => Number.isFinite(item.memory));
  if (!samples.length) {
    return '';
  }
  return samples
    .map((item, index) => `${index === 0 ? 'M' : 'L'} ${xForTime(item.time).toFixed(1)} ${yForCpu(item.memory).toFixed(1)}`)
    .join(' ');
});

const areaPath = computed(() => {
  if (lineSamples.value.length < 2) {
    return '';
  }
  const first = lineSamples.value[0];
  const last = lineSamples.value[lineSamples.value.length - 1];
  return `${linePath.value} L ${xForTime(last.time).toFixed(1)} ${plotBottom.value} L ${xForTime(first.time).toFixed(1)} ${plotBottom.value} Z`;
});

const tooltipStyle = computed(() => {
  const width = 240;
  const left = Math.min(Math.max(8, tooltip.x + 12), Math.max(8, chartWidth.value - width - 8));
  const top = Math.max(8, tooltip.y - 10);
  return {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
  };
});

onMounted(() => {
  measure();
  if (window.ResizeObserver && chartRoot.value) {
    resizeObserver = new ResizeObserver(measure);
    resizeObserver.observe(chartRoot.value);
  } else {
    window.addEventListener('resize', measure);
  }
});

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect();
  }
  window.removeEventListener('resize', measure);
});

function measure() {
  if (!chartRoot.value) {
    return;
  }
  const rect = chartRoot.value.getBoundingClientRect();
  chartWidth.value = Math.max(320, Math.round(rect.width || chartRoot.value.clientWidth || 900));
  const fallbackHeight = window.innerHeight ? window.innerHeight - rect.top - 22 : 640;
  chartHeight.value = Math.max(MIN_CHART_HEIGHT, Math.round(rect.height || chartRoot.value.clientHeight || fallbackHeight));
}

function yForCpu(cpu) {
  return plotBottom.value - (Math.max(0, Math.min(100, cpu)) / 100) * plotHeight.value;
}

function laneY(lane) {
  return Math.max(
    plotTop.value + 6,
    plotBottom.value - TASK_AREA_PADDING - ((lane + 1) * TASK_LANE_HEIGHT),
  );
}

function laneCenterY(lane) {
  return laneY(lane) + TASK_BAR_HEIGHT / 2;
}

function handleMouseMove(event) {
  if (dragging.value) {
    return;
  }
  showSampleTooltip(event);
}

function handleMouseLeave() {
  if (!dragging.value) {
    clearTooltip();
  }
}

function showSampleTooltip(event) {
  if (!visibleSamples.value.length) {
    clearTooltip();
    return;
  }
  const x = pointX(event);
  const y = pointY(event);
  if (x < margin.left || x > plotRight.value || y < plotTop.value || y > plotBottom.value) {
    clearTooltip();
    return;
  }
  const targetTime = timeForX(x);
  const nearest = visibleSamples.value.reduce((best, item) => (
    Math.abs(item.time - targetTime) < Math.abs(best.time - targetTime) ? item : best
  ));
  if (Math.abs(xForTime(nearest.time) - x) > 24) {
    clearTooltip();
    return;
  }
  hoverSample.value = nearest;
  tooltip.open = true;
  tooltip.title = formatFullTime(nearest.time);
  tooltip.lines = [
    `CPU ${nearest.cpu.toFixed(1)}%`,
    Number.isFinite(nearest.memory) ? `内存 ${nearest.memory.toFixed(1)}%` : '',
  ].filter(Boolean);
  tooltip.x = x;
  tooltip.y = y;
}

function showTaskTooltip(block, event) {
  hoverSample.value = null;
  tooltip.open = true;
  tooltip.title = block.label;
  tooltip.lines = [
    `开始 ${block.start_time}`,
    block.running ? '运行中' : `结束 ${block.end_time || formatFullTime(block.end)}`,
    `耗时 ${formatDuration(block.start, block.end)}`,
    block.group_name || block.folder_name ? `${block.group_name || '-'} / ${block.folder_name || '-'}` : '',
  ].filter(Boolean);
  tooltip.x = pointX(event);
  tooltip.y = pointY(event);
}

function clearTooltip() {
  hoverSample.value = null;
  tooltip.open = false;
}

function taskTitle(block) {
  return [
    block.label,
    block.start_time,
    block.running ? '运行中' : (block.end_time || formatFullTime(block.end)),
  ].filter(Boolean).join(' · ');
}
</script>

<style scoped>
.cpu-timeline {
  position: relative;
  height: 100%;
  min-height: 300px;
  overflow: hidden;
  touch-action: none;
}

.cpu-timeline.dragging {
  cursor: grabbing;
}

.cpu-svg {
  display: block;
  width: 100%;
  height: 100%;
}

.task-tracks line {
  stroke: var(--line);
  stroke-dasharray: 2 6;
  stroke-width: 1;
}

.task-block {
  stroke: rgba(255, 255, 255, 0.48);
  stroke-width: 1;
}

.task-block.running {
  stroke: #ede9fe;
  stroke-width: 2;
}

.task-block.failed {
  fill: var(--danger);
}

.task-block-label {
  fill: #ffffff;
  font-size: 11px;
  font-weight: 800;
  pointer-events: none;
}

.cpu-plot-bg {
  fill: var(--panel-soft);
  stroke: var(--line);
}

.cpu-grid line {
  stroke: var(--line);
  stroke-width: 1;
}

.cpu-grid text {
  fill: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
}

.cpu-area {
  fill: var(--brand-soft);
  pointer-events: none;
}

.cpu-line {
  fill: none;
  stroke: var(--brand);
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.4;
  pointer-events: none;
}

.memory-line {
  fill: none;
  stroke: var(--ink-strong);
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.2;
  pointer-events: none;
}

.cpu-hover line {
  stroke: var(--muted);
  stroke-dasharray: 3 4;
}

.cpu-hover circle {
  fill: var(--brand);
  stroke: var(--panel);
  stroke-width: 2;
}

.cpu-hover .memory-dot {
  fill: var(--ink-strong);
}

.cpu-tooltip {
  position: absolute;
  z-index: 2;
  display: grid;
  gap: 4px;
  padding: 9px 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  color: var(--ink);
  background: var(--panel);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.16);
  pointer-events: none;
}

.cpu-tooltip strong {
  color: var(--ink-strong);
  font-size: 12px;
}

.cpu-tooltip span {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.4;
  word-break: break-word;
}

.cpu-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted);
  pointer-events: none;
}

.cpu-empty strong {
  color: var(--ink-strong);
}
</style>
