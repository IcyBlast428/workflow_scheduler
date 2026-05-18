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
      :viewBox="`0 0 ${chartWidth} ${chartHeight}`"
      role="img"
      aria-label="CPU timeline"
    >
      <rect class="cpu-plot-bg" :x="margin.left" :y="margin.top" :width="plotWidth" :height="plotHeight" rx="8" />

      <g class="cpu-grid">
        <g v-for="tick in yTicks" :key="tick">
          <line :x1="margin.left" :x2="plotRight" :y1="yForCpu(tick)" :y2="yForCpu(tick)" />
          <text :x="margin.left - 10" :y="yForCpu(tick) + 4" text-anchor="end">{{ tick }}%</text>
        </g>
        <g v-for="tick in xTicks" :key="tick.time">
          <line :x1="xForTime(tick.time)" :x2="xForTime(tick.time)" :y1="margin.top" :y2="plotBottom" />
          <text :x="xForTime(tick.time)" :y="chartHeight - 18" text-anchor="middle">{{ tick.label }}</text>
        </g>
      </g>

      <path v-if="areaPath" class="cpu-area" :d="areaPath" />
      <path v-if="linePath" class="cpu-line" :d="linePath" />

      <g
        v-for="marker in visibleMarkers"
        :key="`${marker.id}-${marker.start_time}`"
        class="cpu-marker"
        @mouseenter="showMarkerTooltip(marker, $event)"
        @mousemove="showMarkerTooltip(marker, $event)"
        @mouseleave="clearTooltip"
      >
        <line :x1="xForTime(marker.time)" :x2="xForTime(marker.time)" :y1="margin.top" :y2="plotBottom" />
        <path :d="markerPath(marker)" />
        <title>{{ markerTitle(marker) }}</title>
      </g>

      <g v-if="hoverSample" class="cpu-hover">
        <line :x1="xForTime(hoverSample.time)" :x2="xForTime(hoverSample.time)" :y1="margin.top" :y2="plotBottom" />
        <circle :cx="xForTime(hoverSample.time)" :cy="yForCpu(hoverSample.cpu)" r="4" />
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
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';

const props = defineProps({
  samples: { type: Array, default: () => [] },
  markers: { type: Array, default: () => [] },
  retentionHours: { type: Number, default: 6 },
});

const chartRoot = ref(null);
const chartWidth = ref(900);
const chartHeight = 360;
const margin = { top: 22, right: 24, bottom: 48, left: 56 };
const viewStart = ref(0);
const viewEnd = ref(0);
const userNavigated = ref(false);
const dragging = ref(false);
const dragLastX = ref(0);
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
const plotBottom = computed(() => chartHeight - margin.bottom);
const plotWidth = computed(() => Math.max(1, chartWidth.value - margin.left - margin.right));
const plotHeight = computed(() => Math.max(1, chartHeight - margin.top - margin.bottom));

const normalizedSamples = computed(() => props.samples
  .map((item) => {
    const time = parseTime(item.time || item.datetime || item.timestamp);
    const cpu = Number(item.cpu ?? item.value ?? item.usage);
    if (!Number.isFinite(time) || !Number.isFinite(cpu)) {
      return null;
    }
    return {
      time,
      cpu: Math.max(0, Math.min(100, cpu)),
      raw: item,
    };
  })
  .filter(Boolean)
  .sort((left, right) => left.time - right.time));

const normalizedMarkers = computed(() => props.markers
  .map((item) => {
    const time = parseTime(item.start_time || item.time || item.datetime);
    if (!Number.isFinite(time)) {
      return null;
    }
    return {
      ...item,
      time,
      start_time: item.start_time || formatFullTime(time),
    };
  })
  .filter(Boolean)
  .sort((left, right) => left.time - right.time));

const fullRange = computed(() => {
  const retentionMs = Math.max(1, props.retentionHours || 6) * 60 * 60 * 1000;
  const now = Date.now();
  const dataTimes = [
    ...normalizedSamples.value.map((item) => item.time),
    ...normalizedMarkers.value.map((item) => item.time),
  ].filter(Number.isFinite);
  const maxDataTime = dataTimes.length ? Math.max(...dataTimes) : now;
  const minDataTime = dataTimes.length ? Math.min(...dataTimes) : now;
  const end = Math.max(maxDataTime, now);
  let start = Math.max(minDataTime, end - retentionMs);
  const minimumSpan = 5 * 60 * 1000;
  if (end - start < minimumSpan) {
    start = end - minimumSpan;
  }
  return { start, end };
});

const visibleSamples = computed(() => normalizedSamples.value.filter((item) => (
  item.time >= viewStart.value && item.time <= viewEnd.value
)));

const lineSamples = computed(() => {
  return visibleSamples.value.slice();
});

const visibleMarkers = computed(() => normalizedMarkers.value.filter((item) => (
  item.time >= viewStart.value && item.time <= viewEnd.value
)));

const yTicks = [100, 75, 50, 25, 0];

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

const areaPath = computed(() => {
  if (lineSamples.value.length < 2) {
    return '';
  }
  const first = lineSamples.value[0];
  const last = lineSamples.value[lineSamples.value.length - 1];
  return `${linePath.value} L ${xForTime(last.time).toFixed(1)} ${plotBottom.value} L ${xForTime(first.time).toFixed(1)} ${plotBottom.value} Z`;
});

const tooltipStyle = computed(() => {
  const width = 220;
  const left = Math.min(Math.max(8, tooltip.x + 12), Math.max(8, chartWidth.value - width - 8));
  const top = Math.max(8, tooltip.y - 10);
  return {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
  };
});

watch(fullRange, (range, previous) => {
  if (!viewStart.value || !viewEnd.value || !userNavigated.value) {
    viewStart.value = range.start;
    viewEnd.value = range.end;
    return;
  }

  const span = viewEnd.value - viewStart.value;
  const wasAtEnd = previous ? Math.abs(viewEnd.value - previous.end) < 30 * 1000 : false;
  if (wasAtEnd) {
    setDomain(range.end - span, range.end);
  } else {
    setDomain(viewStart.value, viewEnd.value);
  }
}, { immediate: true });

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
  removeDragListeners();
});

function measure() {
  if (!chartRoot.value) {
    return;
  }
  chartWidth.value = Math.max(320, Math.round(chartRoot.value.clientWidth || 900));
}

function parseTime(value) {
  if (typeof value === 'number') {
    return value;
  }
  const text = String(value || '').trim();
  if (!text) {
    return NaN;
  }
  return new Date(text.replace(' ', 'T')).getTime();
}

function formatFullTime(time) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(time));
}

function formatTick(time, span) {
  const options = span > 12 * 60 * 60 * 1000
    ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }
    : { hour: '2-digit', minute: '2-digit', hour12: false };
  return new Intl.DateTimeFormat('zh-CN', options).format(new Date(time));
}

function xForTime(time) {
  const span = Math.max(1, viewEnd.value - viewStart.value);
  return margin.left + ((time - viewStart.value) / span) * plotWidth.value;
}

function yForCpu(cpu) {
  return plotBottom.value - (Math.max(0, Math.min(100, cpu)) / 100) * plotHeight.value;
}

function timeForX(x) {
  const ratio = (Math.max(margin.left, Math.min(plotRight.value, x)) - margin.left) / plotWidth.value;
  return viewStart.value + ratio * (viewEnd.value - viewStart.value);
}

function setDomain(start, end) {
  const range = fullRange.value;
  const minimumSpan = 60 * 1000;
  const maximumSpan = Math.max(minimumSpan, range.end - range.start);
  let span = Math.max(minimumSpan, Math.min(maximumSpan, end - start));
  let nextStart = start;
  let nextEnd = start + span;

  if (nextStart < range.start) {
    nextStart = range.start;
    nextEnd = nextStart + span;
  }
  if (nextEnd > range.end) {
    nextEnd = range.end;
    nextStart = nextEnd - span;
  }
  if (nextStart < range.start) {
    span = range.end - range.start;
    nextStart = range.start;
    nextEnd = range.start + span;
  }

  viewStart.value = nextStart;
  viewEnd.value = nextEnd;
}

function pointX(event) {
  const rect = chartRoot.value.getBoundingClientRect();
  return event.clientX - rect.left;
}

function pointY(event) {
  const rect = chartRoot.value.getBoundingClientRect();
  return event.clientY - rect.top;
}

function handleWheel(event) {
  if (!normalizedSamples.value.length && !normalizedMarkers.value.length) {
    return;
  }
  event.preventDefault();
  userNavigated.value = true;
  const x = Math.max(margin.left, Math.min(plotRight.value, pointX(event)));
  const center = timeForX(x);
  const span = viewEnd.value - viewStart.value;
  const nextSpan = span * (event.deltaY > 0 ? 1.25 : 0.8);
  const ratio = (center - viewStart.value) / span;
  setDomain(center - nextSpan * ratio, center + nextSpan * (1 - ratio));
}

function handleMouseDown(event) {
  if (event.button !== 1) {
    return;
  }
  event.preventDefault();
  dragging.value = true;
  userNavigated.value = true;
  dragLastX.value = event.clientX;
  window.addEventListener('mousemove', handleWindowDrag);
  window.addEventListener('mouseup', handleMouseUp);
}

function handleWindowDrag(event) {
  if (!dragging.value) {
    return;
  }
  event.preventDefault();
  panByPixels(event.clientX - dragLastX.value);
  dragLastX.value = event.clientX;
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

function handleMouseUp() {
  dragging.value = false;
  removeDragListeners();
}

function removeDragListeners() {
  window.removeEventListener('mousemove', handleWindowDrag);
  window.removeEventListener('mouseup', handleMouseUp);
}

function panByPixels(deltaX) {
  const span = viewEnd.value - viewStart.value;
  const deltaTime = -(deltaX / plotWidth.value) * span;
  setDomain(viewStart.value + deltaTime, viewEnd.value + deltaTime);
}

function showSampleTooltip(event) {
  if (!visibleSamples.value.length) {
    clearTooltip();
    return;
  }
  const x = pointX(event);
  const y = pointY(event);
  if (x < margin.left || x > plotRight.value || y < margin.top || y > plotBottom.value) {
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
  tooltip.lines = [`CPU ${nearest.cpu.toFixed(1)}%`];
  tooltip.x = x;
  tooltip.y = y;
}

function showMarkerTooltip(marker, event) {
  hoverSample.value = null;
  tooltip.open = true;
  tooltip.title = marker.id || '任务';
  tooltip.lines = [
    marker.name || marker.id || '',
    marker.start_time,
    marker.group_name || marker.folder_name ? `${marker.group_name || '-'} / ${marker.folder_name || '-'}` : '',
  ].filter(Boolean);
  tooltip.x = pointX(event);
  tooltip.y = pointY(event);
}

function clearTooltip() {
  hoverSample.value = null;
  tooltip.open = false;
}

function markerPath(marker) {
  const x = xForTime(marker.time);
  const y = margin.top + 10;
  return `M ${x.toFixed(1)} ${y - 6} L ${(x + 5).toFixed(1)} ${y.toFixed(1)} L ${x.toFixed(1)} ${y + 6} L ${(x - 5).toFixed(1)} ${y.toFixed(1)} Z`;
}

function markerTitle(marker) {
  return [marker.id, marker.name, marker.start_time].filter(Boolean).join(' · ');
}
</script>

<style scoped>
.cpu-timeline {
  position: relative;
  min-height: 360px;
  overflow: hidden;
  touch-action: none;
}

.cpu-timeline.dragging {
  cursor: grabbing;
}

.cpu-svg {
  display: block;
  width: 100%;
  height: 360px;
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
  fill: rgba(56, 189, 248, 0.14);
  pointer-events: none;
}

.cpu-line {
  fill: none;
  stroke: #38bdf8;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.4;
  pointer-events: none;
}

.cpu-marker line {
  stroke: #f59e0b;
  stroke-dasharray: 4 4;
  stroke-width: 1.4;
}

.cpu-marker path {
  fill: #f59e0b;
  stroke: var(--panel);
  stroke-width: 1.4;
}

.cpu-hover line {
  stroke: var(--muted);
  stroke-dasharray: 3 4;
}

.cpu-hover circle {
  fill: #38bdf8;
  stroke: var(--panel);
  stroke-width: 2;
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
