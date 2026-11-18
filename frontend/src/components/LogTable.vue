<template>
  <div v-if="error" class="error-state">{{ error }}</div>
  <div v-if="!rows.length && !error" class="empty-state">
    <strong>{{ emptyHeading }}</strong>
    <span>{{ emptyHint }}</span>
    <div v-if="!loading && kind === 'task'" class="filter-actions">
      <button v-if="canExpandDates" class="btn" type="button" @click="$emit('expand-dates')">扩大日期范围</button>
      <button v-if="filtered" class="btn" type="button" @click="$emit('reset')">清除筛选</button>
      <button class="btn" type="button" @click="$emit('tasks')">查看任务列表</button>
    </div>
  </div>
  <div v-else-if="rows.length" class="table-wrap" :class="{
    'log-table-desktop': kind === 'task',
    'has-hidden-log-columns': kind === 'task' && visibleColumns.size < defaultDesktopLogColumns.length,
  }">
    <table>
      <thead>
        <tr v-if="kind === 'task'">
          <th v-if="visibleColumns.has('id')" scope="col">{{ logColumnLabels.id }}</th>
          <th scope="col">任务名称</th>
          <th v-if="visibleColumns.has('group')" scope="col">{{ logColumnLabels.group }}</th>
          <th v-if="visibleColumns.has('folder')" scope="col">{{ logColumnLabels.folder }}</th>
          <th v-if="visibleColumns.has('status')" scope="col">{{ logColumnLabels.status }}</th>
          <th v-if="visibleColumns.has('duration')" scope="col">{{ logColumnLabels.duration }}</th>
          <th v-if="visibleColumns.has('start')" scope="col">{{ logColumnLabels.start }}</th>
          <th v-if="visibleColumns.has('end')" scope="col">{{ logColumnLabels.end }}</th>
          <th scope="col">操作</th>
        </tr>
        <tr v-else>
          <th>任务 ID</th>
          <th>任务名称</th>
          <th>报错时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="`${row.logid || row.id}-${row.datetime}`">
          <template v-if="kind === 'task'">
            <td v-if="visibleColumns.has('id')" class="mono cell-strong">{{ row.id }}</td>
            <td>{{ row.name || row.id }}</td>
            <td v-if="visibleColumns.has('group')" class="mono">{{ row.group_name || '-' }}</td>
            <td v-if="visibleColumns.has('folder')" class="mono">{{ row.folder_name || '-' }}</td>
            <td v-if="visibleColumns.has('status')"><span class="tag" :class="statusClass(row.state)">{{ row.state }}</span></td>
            <td v-if="visibleColumns.has('duration')">{{ row.times || '-' }}</td>
            <td v-if="visibleColumns.has('start')" class="nowrap">{{ displayDateTime(row.starttime) }}</td>
            <td v-if="visibleColumns.has('end')" class="nowrap">{{ displayDateTime(row.datetime) }}</td>
          </template>
          <template v-else>
            <td class="mono cell-strong">{{ row.id }}</td>
            <td>{{ row.name }}</td>
            <td class="nowrap">{{ row.datetime || '-' }}</td>
          </template>
          <td>
            <button class="btn" type="button" @click="$emit('open', row)">详情</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <ul v-if="kind === 'task' && rows.length" class="log-records-mobile" role="list" aria-label="执行记录">
    <li v-for="row in rows" :key="`${row.logid || row.id}-${row.datetime}`">
      <button class="log-record-button" type="button" @click="$emit('open', row)">
        <span class="log-record-summary">
          <strong>{{ row.name || row.id }}</strong>
          <span v-if="visibleColumns.has('id')" class="log-record-meta">{{ logColumnLabels.id }} {{ row.id }}</span>
          <span v-if="visibleColumns.has('group')" class="log-record-meta">{{ logColumnLabels.group }} {{ row.group_name || '—' }}</span>
          <span v-if="visibleColumns.has('folder')" class="log-record-meta">{{ logColumnLabels.folder }} {{ row.folder_name || '—' }}</span>
          <span v-if="visibleColumns.has('duration')" class="log-record-meta">{{ logColumnLabels.duration }} {{ row.times || '—' }}</span>
          <span v-if="visibleColumns.has('start')" class="log-record-meta">开始 {{ displayDateTime(row.starttime, '—') }}</span>
          <span v-if="visibleColumns.has('end')" class="log-record-meta">结束 {{ displayDateTime(row.datetime, '—') }}</span>
        </span>
        <span class="log-record-actions">
          <span v-if="visibleColumns.has('status')" class="tag" :class="statusClass(row.state)">{{ row.state || '未知' }}</span>
          <span>详情 <span aria-hidden="true">›</span></span>
        </span>
      </button>
    </li>
  </ul>
</template>

<script setup>
import { computed } from 'vue';
import { statusClass } from '../executionLabels';
import { displayDateTime } from '../timebase';
import { defaultDesktopLogColumns, logColumnLabels } from '../logColumns';

const props = defineProps({
  kind: { type: String, required: true },
  rows: { type: Array, required: true },
  columns: { type: Array, default: () => [...defaultDesktopLogColumns] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  filtered: Boolean,
  scope: { type: String, default: 'online' },
  canExpandDates: Boolean,
});
const visibleColumns = computed(() => new Set(props.columns));

const emptyHeading = computed(() => {
  if (props.loading) return '正在读取记录';
  if (props.kind === 'task' && props.scope === 'archive') return '没有匹配的归档记录';
  return props.filtered ? '没有匹配的记录' : '当前时间范围内没有记录';
});

const emptyHint = computed(() => {
  if (props.loading) return '正在更新结果，请稍候。';
  if (props.kind === 'system') return '这段时间没有平台事件。';
  if (props.scope === 'archive') {
    return props.canExpandDates
      ? '可以扩大日期范围，或将查询范围改为「近期与归档」。'
      : '可以改查另一段日期，或将查询范围改为「近期与归档」。';
  }
  if (props.filtered) return '可以调整日期范围或清除筛选。';
  return '可扩大日期范围，或将查询范围改为「近期与归档」以查找更早的执行。';
});

defineEmits(['open', 'reset', 'tasks', 'expand-dates']);
</script>

<style scoped>
.has-hidden-log-columns table { min-width: 100%; }
.has-hidden-log-columns td:not(.nowrap) { overflow-wrap: anywhere; }
.log-records-mobile { display: none; }

@media (max-width: 760px) {
  .log-table-desktop { display: none; }
  .log-records-mobile {
    display: grid;
    gap: 8px;
    list-style: none;
    margin: 0;
    padding: 0 var(--panel-padding) 12px;
    border-top: 0;
  }
  .log-record-button {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 12px;
    align-items: center;
    width: 100%;
    padding: 12px;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--panel-soft);
    color: var(--ink);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .log-record-button:hover { background: var(--row-hover); }
  .log-record-button:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
  .log-record-summary, .log-record-actions {
    display: grid;
    gap: 6px;
    overflow-wrap: anywhere;
  }
  .log-record-actions {
    justify-items: end;
    font-size: 12px;
    color: var(--muted-strong);
  }
  .log-record-meta { color: var(--muted); font-size: 12px; }
}
</style>
