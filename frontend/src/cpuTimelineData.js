// Data preparation is independent of Vue and the chart viewport.
import {timestamp, BUSINESS_TIMEZONE} from './timebase.js';
export const MAX_TASK_LANES = 20;

export const normalizeSamples = (samples) => samples
  .map((item) => {
    const time = parseTime(item.time || item.datetime || item.timestamp);
    const cpu = Number(item.cpu ?? item.value ?? item.usage);
    const memory = Number(item.memory ?? item.mem ?? item.memory_percent);
    if (!Number.isFinite(time) || !Number.isFinite(cpu)) {
      return null;
    }
    return {
      time,
      cpu: Math.max(0, Math.min(100, cpu)),
      memory: Number.isFinite(memory) ? Math.max(0, Math.min(100, memory)) : null,
      raw: item,
    };
  })
  .filter(Boolean)
  .sort((left, right) => left.time - right.time);

export function normalizeTasks(markers, now = Date.now()) {
  const tasks = markers.map((item, index) => {
    const start = parseTime(item.start_time || item.time || item.datetime);
    let end = parseTime(item.end_time);
    if (!Number.isFinite(start)) {
      return null;
    }
    const running = !Number.isFinite(end);
    if (running) {
      end = Math.max(now, start + 1000);
    }
    if (end <= start) {
      end = start + 1000;
    }
    return {
      ...item,
      index,
      start,
      end,
      running,
      start_time: item.start_time || formatFullTime(start),
      end_time: item.end_time || '',
      label: taskLabel(item),
      failed: Number(item.state) !== 0 && item.state !== undefined && item.state !== null && item.state !== '',
    };
  })
    .filter(Boolean);

  return mergeTaskBlocks(tasks)
    .sort((left, right) => left.start - right.start || left.end - right.end);
}

export function timelineRange(samples, tasks, retentionHours = 6, now = Date.now()) {
  const retentionMs = Math.max(1, retentionHours || 6) * 60 * 60 * 1000;
  const dataTimes = [
    ...samples.map((item) => item.time),
    ...tasks.flatMap((item) => [item.start, item.end]),
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
}

export function layoutTaskLanes(tasks, span, plotWidth) {
  const laneEnds = [];
  const gapMs = (span / plotWidth) * 4;
  return tasks.map((task) => {
    let lane = laneEnds.findIndex((end) => task.start >= end + gapMs);
    if (lane === -1) {
      lane = laneEnds.length < MAX_TASK_LANES ? laneEnds.length : leastBusyLane(laneEnds);
    }
    laneEnds[lane] = Math.max(laneEnds[lane] || 0, task.end);
    return { ...task, lane };
  });
}

export function parseTime(value) {
  if (typeof value === 'number') {
    return value;
  }
  const text = String(value || '').trim();
  if (!text) {
    return NaN;
  }
  return timestamp(text);
}

export function formatFullTime(time) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: BUSINESS_TIMEZONE,
  }).format(new Date(time));
}

export function formatTick(time, span) {
  const options = span > 12 * 60 * 60 * 1000
    ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }
    : { hour: '2-digit', minute: '2-digit', hour12: false };
  return new Intl.DateTimeFormat('zh-CN', {...options,timeZone:BUSINESS_TIMEZONE}).format(new Date(time));
}

export function formatDuration(start, end) {
  const seconds = Math.max(1, Math.round((end - start) / 1000));
  if (seconds < 60) {
    return `${seconds} 秒`;
  }
  const minutes = Math.floor(seconds / 60);
  const remain = seconds % 60;
  if (minutes < 60) {
    return remain ? `${minutes} 分 ${remain} 秒` : `${minutes} 分`;
  }
  const hours = Math.floor(minutes / 60);
  const minuteRemain = minutes % 60;
  return minuteRemain ? `${hours} 小时 ${minuteRemain} 分` : `${hours} 小时`;
}

export function taskLabel(task) {
  const id = task.id || '任务';
  const name = task.name && task.name !== id ? task.name : '';
  return name ? `${id} · ${name}` : id;
}

export function hashText(text) {
  return String(text || '').split('').reduce((total, char) => (
    ((total << 5) - total) + char.charCodeAt(0)
  ), 0);
}

export function taskColor(task) {
  if (task.failed) {
    return '#dc2626';
  }
  if (task.running) {
    return '#7c3aed';
  }
  return '#16a34a';
}

function shouldMergeTaskBlock(left, right) {
  if ((left.id || '') !== (right.id || '')) {
    return false;
  }
  const startGap = Math.abs(left.start - right.start);
  if (startGap > 2000) {
    return false;
  }
  const overlaps = Math.min(left.end, right.end) >= Math.max(left.start, right.start) - 1000;
  const similarEnd = Math.abs(left.end - right.end) <= 5000;
  return overlaps || similarEnd;
}

function mergeTaskBlock(left, right) {
  const completed = !left.running || !right.running;
  const preferred = right.source === 'history' ? right : left;
  return {
    ...left,
    ...preferred,
    start: Math.min(left.start, right.start),
    end: Math.max(left.end, right.end),
    running: !completed,
    failed: left.failed || right.failed,
    start_time: left.start <= right.start ? left.start_time : right.start_time,
    end_time: right.end_time || left.end_time || '',
    label: taskLabel({
      id: left.id || right.id,
      name: preferred.name || left.name || right.name,
    }),
  };
}

export function mergeTaskBlocks(tasks) {
  const merged = [];
  tasks
    .slice()
    .sort((left, right) => (left.id || '').localeCompare(right.id || '') || left.start - right.start)
    .forEach((task) => {
      const index = merged.findIndex((item) => shouldMergeTaskBlock(item, task));
      if (index === -1) {
        merged.push(task);
        return;
      }
      merged[index] = mergeTaskBlock(merged[index], task);
    });
  return merged;
}

function leastBusyLane(laneEnds) {
  let lane = 0;
  let value = laneEnds[0] || 0;
  laneEnds.forEach((item, index) => {
    if (item < value) {
      lane = index;
      value = item;
    }
  });
  return lane;
}
