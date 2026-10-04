<template>
  <div v-if="error" class="error-state">{{ error }}</div>
  <div v-if="!rows.length && !error" class="empty-state">
    <strong>{{ loading ? '正在读取记录' : filtered ? '没有匹配的记录' : '当前时间范围内没有记录' }}</strong>
    <span>{{ loading ? '正在更新结果，请稍候。' : filtered ? '可以清除筛选，或选择更宽的时间范围。' : kind === 'task' ? '任务可能尚未执行。更早的记录可切换到归档范围查询。' : '这段时间没有平台事件。' }}</span>
<div v-if="!loading && kind === 'task'" class="filter-actions"><button v-if="filtered" class="btn" @click="$emit('reset')">清除筛选</button><button class="btn" @click="$emit('tasks')">查看任务列表</button></div>
  </div>
  <div v-else-if="rows.length" class="table-wrap">
    <table>
      <thead>
        <tr v-if="kind === 'task'">
          <th>任务 ID</th>
          <th>任务名称</th>
          <th>组名</th>
          <th>任务目录</th>
          <th>状态</th>
          <th>耗时</th>
          <th>开始时间</th>
          <th>结束时间</th>
          <th>操作</th>
        </tr>
        <tr v-else>
          <th>任务 ID</th>
          <th>任务名称</th>
          <th>报错时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="`${row.id}-${row.datetime}-${index}`">
          <template v-if="kind === 'task'">
            <td class="mono cell-strong">{{ row.id }}</td>
            <td>{{ row.name }}</td>
            <td class="mono">{{ row.group_name || '-' }}</td>
            <td class="mono">{{ row.folder_name || '-' }}</td>
            <td><span class="tag" :class="statusClass(row.state)">{{ row.state }}</span></td>
            <td>{{ row.times || '-' }}</td>
            <td class="nowrap">{{ row.starttime || '-' }}</td>
            <td class="nowrap">{{ row.datetime || '-' }}</td>
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
</template>

<script setup>
import { statusClass } from '../executionLabels';
defineProps({
  kind: { type: String, required: true },
  rows: { type: Array, required: true },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  filtered: Boolean,
});

defineEmits(['open','reset','tasks']);
</script>
