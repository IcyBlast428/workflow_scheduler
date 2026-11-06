<template>
  <div class="summary-grid dashboard-summary">
    <button v-for="item in cards" :key="item.label" class="metric-card" @click="$emit('tasks',item.filter)"><span>{{ item.label }}</span><strong>{{ summary[item.key] || 0 }}</strong><small>{{ item.filter && !summary[item.key] ? '暂无相关任务' : '查看相关任务 →' }}</small></button>
  </div>
  <section class="panel dashboard-issues"><div class="panel-head"><div><h2>{{ failures.length ? '最近失败与执行' : '最近执行' }}</h2><p>最近 24 小时 · 失败统计包含超时</p></div><span v-if="!failures.length" class="quiet-status">✓ 最近 24 小时无脚本失败</span></div>
    <div class="issue-columns" :class="{'recent-only':!failures.length}"><div v-if="failures.length"><h3>失败较多的任务</h3><button v-for="item in failures.slice(0,5)" :key="item.id" class="btn issue-row" @click="$emit('detail',item.id)">{{ item.name }} <span class="tag danger">{{ item.count }} 次</span></button></div>
      <div><h3 v-if="failures.length">最近执行</h3><p v-if="!recent.length" class="hint">还没有执行记录。</p><button v-for="(item,index) in recent.slice(0,5)" :key="index" class="btn issue-row" @click="item.run_id && /^[a-f0-9]{32}$/i.test(item.run_id) ? $emit('execution',item.run_id) : $emit('detail',item.id)"><span class="recent-run-copy"><strong>{{ item.name }}</strong><small :title="item.end_time">{{ displayDateTime(item.end_time) }} · {{ elapsed(item) }}</small></span><span class="tag" :class="exitClass(item.state)">{{ exitLabel(item.state) }}</span></button></div></div>
  </section>
</template>
<script setup>
import { timestamp, displayDateTime } from '../timebase';
import { exitLabel, exitClass } from '../executionLabels';
defineProps({summary:{type:Object,default:()=>({})},failures:{type:Array,default:()=>[]},recent:{type:Array,default:()=>[]}});
defineEmits(['tasks','detail','execution']);
function elapsed(item){const seconds=(timestamp(item.end_time)-timestamp(item.start_time))/1000;return Number.isFinite(seconds)?`${Math.max(0,seconds).toFixed(1)} 秒`:'耗时未记录';}
const cards = [{label:'任务总数',key:'total',filter:''},{label:'有活动实例',key:'pending',filter:'active'},{label:'最近结果异常',key:'failed_jobs',filter:'failed'},{label:'配置异常',key:'invalid',filter:'invalid'}];
</script>

<style scoped>.recent-run-copy{display:grid;gap:6px;min-width:0;text-align:left}.recent-run-copy strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500}.recent-run-copy small{font-size:12px;color:var(--muted)}.issue-row{min-height:60px}.issue-columns.recent-only{grid-template-columns:minmax(0,1fr)}.recent-only .issue-row{min-height:52px}.quiet-status{color:var(--muted);font-size:13px}.dashboard-issues .panel-head{padding-block:14px}.dashboard-issues .panel-head p{margin-bottom:0}.dashboard-summary .metric-card small{color:var(--muted);font-size:12px}.dashboard-summary .metric-card{box-shadow:none}
</style>
