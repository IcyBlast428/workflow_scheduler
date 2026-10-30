<template>
  <div class="table-wrap task-table-wrap">
    <table class="task-table">
      <colgroup>
        <col class="col-name" />
        <col class="col-group" />
        <col class="col-status" />
        <col class="col-pending" />
        <col class="col-result" />
        <col class="col-failed" />
        <col class="col-next" />
        <col class="col-actions" />
      </colgroup>
      <thead>
        <tr>
          <th>任务名称</th>
          <th>组名</th>
          <th>状态</th>
          <th>活动实例 / 上限</th>
          <th>最近结果</th>
          <th>连续 / 累计失败</th>
          <th>下次执行</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.id" :class="change(row.id) ? 'gitlab-row-' + change(row.id).kind : ''">
          <td class="task-name-cell">
            <div class="task-identity">
              <input
                v-if="canOperate"
                type="checkbox"
                :aria-label="`选择任务 ${row.id}`"
                :checked="selected.includes(row.id)"
                :disabled="!permitted(row,'schedule')"
                @change="$emit('select', row.id)"
              />
              <div class="task-name-copy">
                <button
                  class="task-name-link clip"
                  :title="row.name"
                  @click="$emit('detail', row)"
                >
                  {{ row.name }}
                </button>
                <div class="mono muted clip" :title="row.id">{{ row.id }}</div>
                <div class="mobile-task-status"><span class="tag" :class="stateClass(row)">{{ stateText(row) }}</span><span class="tag" :class="lastStatusClass(row.last_status)">{{ lastStatusText(row.last_status) }}</span><small>活动 {{ row.running_instances || 0 }} / {{ row.max_instances || 1 }}</small><small>下次 {{ row.next_run_time || '未安排' }}</small></div>
                <button v-if="canManage && change(row.id)" class="task-change-badge tag" :class="change(row.id).kind === 'delete' ? 'danger' : 'warning'" @click="$emit('release', row.id)">{{ change(row.id).kind === 'delete' ? 'GitLab 已删除 · 确认删除' : 'GitLab 有更新 · 审查发布' }}</button>
                <div
                  v-if="row.config_error"
                  class="muted clip"
                  :title="row.config_error"
                >
                  {{ row.config_error }}
                </div>
                <small
                  v-if="row.application?.status === 'failed'"
                  class="cell-subtitle danger-text"
                  >配置生效失败：{{ row.application.message }}</small
                >
              </div>
            </div>
          </td>
          <td class="mono clip" :title="row.group_name || '-'">
            {{ row.group_name || '-' }}
          </td>
          <td>
            <span class="tag" :class="stateClass(row)">{{
              stateText(row)
            }}</span>
          </td>
          <td>
            <span class="tag" :class="row.pending ? 'brand' : 'info'"
              >{{ row.running_instances || 0 }} /
              {{ row.max_instances || 1 }}</span
            >
          </td>
          <td>
            <span class="tag" :class="lastStatusClass(row.last_status)">{{
              lastStatusText(row.last_status)
            }}</span>
          </td>
          <td>
            <span class="tag" :class="row.failed_times ? 'danger' : 'info'"
              >{{ row.failed_times || 0 }} / {{ row.total_failures || 0 }}</span
            >
          </td>
          <td class="next-run-cell">
            <span class="next-run-value" :title="row.next_run_time || '-'">{{
              row.next_run_time || '-'
            }}</span>
          </td>
          <td class="action-cell">
            <div class="row-actions task-actions">
              <button class="btn" @click="$emit('detail', row)">详情</button>
              <button
                v-if="row.pending"
                class="btn"
                @click="$emit('execution', row)"
              >
                查看执行
              </button>
              <button
                v-else-if="canOperate && permitted(row,'run') && canCallTask(row)"
                class="btn primary"
                type="button"
                :disabled="busy || pendingActions[row.id]"
                :title="callTaskTitle(row)"
                @click="$emit('call', row)"
              >
                手动执行
              </button>
              <ActionMenu>
                <button v-if="permitted(row,'publish')" class="btn" @click="$emit('release', row.id)">代码版本</button>
                <button
                  v-if="canOperate && permitted(row,'schedule') && canStart(row)"
                  class="btn"
                  :disabled="busy || pendingActions[row.id]"
                  @click="$emit('action', row, 'start')"
                >
                  启用调度
                </button>
                <button
                  v-if="canOperate && permitted(row,'schedule') && row.state === 'true'"
                  class="btn"
                  :disabled="busy || pendingActions[row.id]"
                  @click="$emit('pause', row)"
                >
                  暂停调度
                </button>
                <button
                  v-if="permitted(row,'schedule')"
                  class="btn"
                  :disabled="busy || pendingActions[row.id]"
                  @click="$emit('schedule', row)"
                >
                  配置
                </button>
                <button
                  v-if="canOperate && permitted(row,'schedule') && row.state !== 'invalid'"
                  class="btn"
                  :disabled="busy || pendingActions[row.id]"
                  @click="$emit('action', row, 'refresh')"
                >
                  {{
                    pendingActions[row.id] === 'refresh' ? '刷新中…' : '刷新'
                  }}
                </button>
                <button
                  class="btn"
                  :disabled="pendingActions[row.id]"
                  @click="$emit('log', row)"
                >
                  最新输出
                </button>
                <button
                  v-if="canOperate && row.pending"
                  class="btn danger"
                  :disabled="busy || pendingActions[row.id]"
                  @click="$emit('action', row, 'kill')"
                >
                  强停
                </button>
                <button
                  class="btn favorite-button"
                  :class="{ 'is-favorite': favorites.includes(row.id) }"
                  :aria-pressed="favorites.includes(row.id)"
                  :aria-label="`${favorites.includes(row.id) ? '取消收藏' : '收藏'}任务 ${row.id}`"
                  @click="$emit('favorite', row.id)"
                >
                  <span aria-hidden="true">{{
                    favorites.includes(row.id) ? '★' : '☆'
                  }}</span>
                  {{ favorites.includes(row.id) ? '已收藏' : '收藏' }}
                </button>
              </ActionMenu>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import ActionMenu from './ActionMenu.vue';
import { canTrigger, exitLabel, exitClass } from '../executionLabels';
const props = defineProps({
  rows: { type: Array, required: true },
  favorites: { type: Array, default: () => [] },
  selected: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  pendingActions: { type: Object, default: () => ({}) },
  canOperate: { type: Boolean, default: true },
  canManage: { type: Boolean, default: true },
  gitlabChanges: { type: Array, default: () => [] },
});
const change = pid => props.gitlabChanges.find(item => item.pid === pid && item.kind !== 'new');

defineEmits([
  'action',
  'pause',
  'call',
  'schedule',
  'log',
  'detail',
  'favorite',
  'select',
  'execution',
  'release',
]);

function permitted(row,capability) { return props.canManage || row.permissions?.includes(capability); }
function stateText(row) {
  if (row.state === 'invalid') {
    return '配置错误';
  }
  if (!row.schedule_configured) {
    return '未配置';
  }
  const map = {
    true: '调度已启用',
    false: row.schedule_enabled ? '已停止' : '未启用',
    pause: '已暂停',
    kill: '已停止',
    error: '异常',
  };
  return map[row.state] || row.state || '未知';
}

function stateClass(row) {
  if (row.state === 'invalid') {
    return 'danger';
  }
  if (!row.schedule_configured) {
    return 'warning';
  }
  const map = {
    true: 'success',
    false: row.schedule_enabled ? 'info' : 'warning',
    pause: 'warning',
    kill: 'info',
    error: 'danger',
  };
  return map[row.state] || 'info';
}

function lastStatusText(status) {
  if (status === null || status === undefined || status === '') {
    return '暂无';
  }
  return exitLabel(status);
}

function lastStatusClass(status) {
  return exitClass(status);
}

function canStart(row) {
  return (
    row.schedule_configured && row.state !== 'true' && row.state !== 'invalid'
  );
}

function canCallTask(row) {
  return canTrigger(row);
}

function callTaskTitle(row) {
  if (row.state === 'invalid') {
    return '入口文件或任务配置错误，不能手动触发';
  }
  if (!canTrigger(row)) {
    return '并发名额已满，请等待正在运行的实例结束';
  }
  if (!row.schedule_configured) {
    return '尚未配置调度，也可以手动执行一次';
  }
  if (row.state === 'pause') {
    return '暂停任务也可以手动执行一次';
  }
  return '立即执行一次任务';
}
</script>
<style scoped>
.gitlab-row-update{background:#d4a54b0a}.gitlab-row-delete{background:#d45c5c0b}.gitlab-row-update .task-name-cell{box-shadow:inset 3px 0 #c5a164}.gitlab-row-delete .task-name-cell{box-shadow:inset 3px 0 #bc6969}.task-change-badge{margin-top:8px;cursor:pointer;text-align:left;white-space:normal;font:inherit;font-size:12px;border:1px solid currentColor}
</style>
