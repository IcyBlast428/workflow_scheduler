<template>
  <div v-if="pid" class="modal-backdrop" @click.self="$emit('close')">
    <section class="modal task-detail-modal">
      <header class="modal-head"><h3>任务详情：{{ pid }}</h3><button class="btn icon-only" title="关闭" @click="$emit('close')">×</button></header>
      <div class="modal-body task-detail-body">
        <div class="detail-toolbar"><div class="filter-actions" aria-label="详情内容"><button v-for="item in tabs" :key="item.id" class="btn" :aria-pressed="tab === item.id" :class="tab === item.id ? 'primary' : ''" @click="selectTab(item.id)">{{ item.label }}</button></div><button class="btn detail-refresh" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新详情' }}</button></div>
        <LoadingStatus :active="loading || (tab === 'source' && sourceLoading)" :label="tab === 'source' && sourceLoading ? '正在读取任务文件…' : '正在更新任务详情…'" />
        <div v-if="error" class="inline-alert danger" role="alert">{{ error }}</div>
        <div class="detail-panels" :aria-busy="loading">
        <div v-show="tab === 'description'" class="detail-tab-panel" aria-label="说明与配置">
          <p>负责人：{{ data.schedule?.form?.owner || '未填写' }} · 入口：{{ data.schedule?.main_file }} · 配置版本：{{ data.schedule?.version || 0 }}</p>
          <p>生效状态：{{ ({applied:'已生效',pending:'待生效',failed:'生效失败',unconfigured:'未配置'})[data.schedule?.application?.status] || '待确认' }} {{ data.schedule?.application?.message }}</p>
          <p>修改人：{{ data.schedule?.updated_by || '-' }} · {{ data.schedule?.updated_at || '-' }}</p>
          <p>并发上限 {{ data.schedule?.max_instances }} · 超时 {{ data.schedule?.timeout_seconds || '不限' }} 秒</p>
          <pre class="log-pre">{{ data.schedule?.form?.description || data.description }}</pre>
          <h4>最近执行耗时</h4><div class="duration-trend"><span v-for="run in (data.runs || []).slice(0,8)" :key="run.run_id" class="tag" :title="run.created_at">{{ statusLabel(run.status) }} · {{ duration(run) }}</span></div>
          <h4>调度诊断</h4><p>全局活动实例 {{ data.diagnostics?.active }} / {{ data.diagnostics?.capacity }} · 下次计划 {{ data.diagnostics?.next_run_time || '暂无' }}</p><p v-if="data.diagnostics?.last_not_started">最近未启动：{{ data.diagnostics.last_not_started.reason }} · {{ data.diagnostics.last_not_started.scheduled_time || data.diagnostics.last_not_started.created_at }}</p>
          <h4>最近告警</h4><p v-for="alert in data.notifications || []" :key="alert.id">{{ alert.channel === 'sms' ? '短信' : '邮件' }} · {{ {pending:'待发送',sending:'发送中',sent:'网关已接受',unknown:'发送结果待核对',failed:'发送失败'}[alert.status] }} · {{ alert.message }} · {{ alert.created_at }}</p><p v-if="!data.notifications?.length" class="hint">暂无告警记录</p>
        </div>
        <div v-show="tab === 'runs'" class="table-wrap detail-tab-panel" aria-label="执行记录"><table><thead><tr><th>执行编号</th><th>状态</th><th>来源 / 操作人</th><th>时间 / 耗时</th><th>操作</th></tr></thead><tbody>
          <tr v-for="run in data.runs || []" :key="run.run_id"><td class="mono">{{ run.run_id.slice(0,12) }}</td><td><span class="tag" :class="statusClass(run.status)">{{ statusLabel(run.status) }}</span><small class="cell-subtitle">{{ run.reason }}</small></td><td>{{ run.source === 'manual' ? '手动' : '自动调度' }} / {{ run.actor }}</td><td>{{ run.created_at }}<small class="cell-subtitle">{{ duration(run) }}</small></td><td><button class="btn" @click="$emit('execution',run.run_id)">查看执行</button></td></tr>
        </tbody></table><p v-if="!data.runs?.length" class="hint">还没有新版本的执行记录；旧历史可在调度日志中查看。</p></div>
        <div v-show="tab === 'versions'" class="table-wrap detail-tab-panel" aria-label="配置历史"><table><thead><tr><th>版本</th><th>修改人</th><th>时间</th><th>操作</th></tr></thead><tbody>
          <tr v-for="item in data.versions || []" :key="item.version"><td>{{ item.version }}</td><td>{{ item.changed_by }}</td><td>{{ item.changed_at }}</td><td><button v-if="canManage" class="btn" :disabled="restoring" @click="restore(item.version)">恢复此配置</button></td></tr>
        </tbody></table><p class="hint">恢复会生成新版本，不删除历史；沿用该版本的调度启用状态。</p></div>
        <div v-show="tab === 'audit'" class="table-wrap detail-tab-panel" aria-label="操作记录"><table><thead><tr><th>操作人</th><th>操作</th><th>结果</th><th>时间</th></tr></thead><tbody><tr v-for="(item,index) in data.audit || []" :key="index"><td>{{ item.actor }}</td><td>{{ actionLabel(item.action) }}</td><td>{{ item.outcome === 'success' ? '成功' : '失败' }}</td><td>{{ item.created_at }}</td></tr></tbody></table></div>
        <div v-if="sourceVisited" v-show="tab === 'source'" class="detail-tab-panel"><TaskSourceViewer :key="pid" :pid="pid" :show-loading-status="false" @loading="sourceLoading = $event" /></div>
        </div>
      </div>
    </section>
  </div>
</template>
<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import { api } from '../api';
import { statusLabel, actionLabel, statusClass } from '../executionLabels';
import TaskSourceViewer from './TaskSourceViewer.vue';
import LoadingStatus from './LoadingStatus.vue';
const props = defineProps({ pid: {type:String,default:''}, canManage:Boolean });
const emit = defineEmits(['close','execution','confirmRestore']);
const data = ref({}), tab = ref('description'), error = ref(''), loading = ref(false), restoring = ref(false);
const sourceVisited = ref(false);
const sourceLoading = ref(false);
function selectTab(id) { if (id === 'source') sourceVisited.value = true; tab.value = id; }
const tabs = [{id:'description',label:'说明与配置'},{id:'source',label:'查看代码'},{id:'runs',label:'执行记录'},{id:'versions',label:'配置历史'},{id:'audit',label:'操作记录'}];
let generation = 0;
async function load() {
  if (!props.pid) return;
  const seq = ++generation; loading.value = true;
  try { const result = await api.taskDetail(props.pid); if (seq === generation) { data.value = result; error.value = ''; } }
  catch (err) { if (seq === generation) error.value = err.message; }
  finally { if (seq === generation) loading.value = false; }
}
function duration(run) {
  if (!run.start_time || !run.end_time) return '尚未结束';
  return `${Math.max(0,(Date.parse(run.end_time.replace(' ','T')) - Date.parse(run.start_time.replace(' ','T'))) / 1000).toFixed(1)} 秒`;
}
function restore(version) { emit('confirmRestore', {pid:props.pid, restore_version:version, version:data.value.schedule.version, done:load}); }
watch(() => props.pid, () => { generation++; tab.value = 'description'; sourceVisited.value = false; sourceLoading.value = false; data.value = {}; error.value = ''; loading.value = false; load(); }, {immediate:true});
onBeforeUnmount(() => generation++);
</script>
