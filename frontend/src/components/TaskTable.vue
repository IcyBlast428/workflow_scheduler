<template>
  <div class="table-wrap task-table-wrap">
    <table class="task-table">
      <colgroup>
        <col class="col-id">
        <col class="col-name">
        <col class="col-group">
        <col class="col-folder">
        <col class="col-status">
        <col class="col-pending">
        <col class="col-result">
        <col class="col-failed">
        <col class="col-next">
        <col class="col-actions">
      </colgroup>
      <thead>
        <tr>
          <th>PID</th>
          <th>任务名称</th>
          <th>组名</th>
          <th>Task 名</th>
          <th>状态</th>
          <th>执行中</th>
          <th>最近结果</th>
          <th>失败次数</th>
          <th>下次执行</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.id">
          <td class="mono cell-strong clip" :title="row.id">{{ row.id }}</td>
          <td>
            <div class="cell-strong clip" :title="row.name">{{ row.name }}</div>
            <div v-if="row.config_error" class="muted clip" :title="row.config_error">{{ row.config_error }}</div>
          </td>
          <td class="mono clip" :title="row.group_name || '-'">{{ row.group_name || '-' }}</td>
          <td class="mono clip" :title="row.folder_name || '-'">{{ row.folder_name || '-' }}</td>
          <td>
            <span class="tag" :class="stateClass(row.state)">{{ stateText(row.state) }}</span>
          </td>
          <td>
            <span class="tag" :class="row.pending ? 'brand' : 'info'">{{ row.pending ? '是' : '否' }}</span>
          </td>
          <td>
            <span class="tag" :class="lastStatusClass(row.last_status)">{{ lastStatusText(row.last_status) }}</span>
          </td>
          <td>
            <span class="tag" :class="row.failed_times ? 'danger' : 'info'">{{ row.failed_times || 0 }}</span>
          </td>
          <td class="next-run-cell">
            <span class="next-run-value" :title="row.next_run_time || '-'">{{ row.next_run_time || '-' }}</span>
          </td>
          <td class="action-cell">
            <div class="row-actions task-actions">
              <button v-if="canStart(row)" class="btn primary" type="button" :disabled="busy" @click="$emit('action', row, 'start')">启动</button>
              <button v-else-if="row.state === 'true'" class="btn warning" type="button" :disabled="busy" @click="$emit('pause', row)">暂停</button>
              <button v-else class="btn placeholder" type="button" disabled aria-hidden="true">启动</button>

              <button v-if="row.pending" class="btn danger" type="button" :disabled="busy" @click="$emit('action', row, 'kill')">强停</button>
              <button v-else class="btn placeholder" type="button" disabled aria-hidden="true">强停</button>

              <button v-if="canCallTask(row)" class="btn primary" type="button" :disabled="busy" :title="callTaskTitle(row)" @click="$emit('call', row)">触发</button>
              <button v-else class="btn placeholder" type="button" disabled aria-hidden="true">触发</button>

              <button class="btn" type="button" :disabled="busy" @click="$emit('schedule', row)">调度</button>
              <button v-if="row.state !== 'invalid'" class="btn" type="button" :disabled="busy" @click="$emit('action', row, 'refresh')">刷新</button>
              <button v-else class="btn placeholder" type="button" disabled aria-hidden="true">刷新</button>
              <button class="btn" type="button" :disabled="busy" @click="$emit('log', row)">日志</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
defineProps({
  rows: { type: Array, required: true },
  busy: { type: Boolean, default: false },
});

defineEmits(['action', 'pause', 'call', 'schedule', 'log']);

function stateText(state) {
  const map = {
    true: '运行中',
    false: '已停止',
    pause: '已暂停',
    kill: '已停止',
    error: '异常',
    invalid: '配置错误',
  };
  return map[state] || state || '未知';
}

function stateClass(state) {
  const map = {
    true: 'success',
    false: 'info',
    pause: 'warning',
    kill: 'info',
    error: 'danger',
    invalid: 'danger',
  };
  return map[state] || 'info';
}

function lastStatusText(status) {
  if (status === null || status === undefined || status === '') {
    return '暂无';
  }
  return Number(status) === 0 ? '成功' : '失败';
}

function lastStatusClass(status) {
  if (status === null || status === undefined || status === '') {
    return 'info';
  }
  return Number(status) === 0 ? 'success' : 'danger';
}

function canStart(row) {
  return row.state !== 'true' && row.state !== 'invalid';
}

function canCallTask(row) {
  return row.state !== 'invalid' && !row.pending;
}

function callTaskTitle(row) {
  if (row.state === 'invalid') {
    return '配置错误的任务不能手动触发';
  }
  if (row.pending) {
    return '任务正在运行，不能重复触发';
  }
  if (row.state === 'pause') {
    return '暂停任务也可以手动执行一次';
  }
  if (row.state !== 'true') {
    return '任务未进入调度，也可以手动执行一次';
  }
  return '立即执行一次任务';
}
</script>
