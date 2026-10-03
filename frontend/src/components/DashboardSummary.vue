<template>
  <div class="summary-grid dashboard-summary">
    <button v-for="item in cards" :key="item.label" class="metric-card" @click="$emit('tasks',item.filter)"><span>{{ item.label }}</span><strong>{{ summary[item.key] || 0 }}</strong><small>查看相关任务</small></button>
  </div>
  <section class="panel dashboard-issues"><div class="panel-head"><div><h2>最近失败与执行</h2><p>按最近 24 个小时分组汇总全部记录；失败含超时，取消、中断和跳过单独分类。</p></div></div>
    <div class="issue-columns"><div><h3>失败较多的任务</h3><p v-if="!failures.length" class="hint">最近没有记录到脚本失败。</p><button v-for="item in failures.slice(0,5)" :key="item.id" class="btn issue-row" @click="$emit('detail',item.id)">{{ item.name }} <span class="tag danger">{{ item.count }} 次</span></button></div>
      <div><h3>最近执行</h3><p v-if="!recent.length" class="hint">还没有执行记录。</p><button v-for="(item,index) in recent.slice(0,5)" :key="index" class="btn issue-row" @click="$emit('detail',item.id)">{{ item.name }} <span>{{ exitLabel(item.state) }}</span></button></div></div>
  </section>
</template>
<script setup>
import { exitLabel } from '../executionLabels';
defineProps({summary:{type:Object,default:()=>({})},failures:{type:Array,default:()=>[]},recent:{type:Array,default:()=>[]}});
defineEmits(['tasks','detail']);
const cards = [{label:'任务总数',key:'total',filter:''},{label:'有活动实例',key:'pending',filter:'active'},{label:'最近结果异常',key:'failed_jobs',filter:'failed'},{label:'配置异常',key:'invalid',filter:'invalid'}];
</script>
