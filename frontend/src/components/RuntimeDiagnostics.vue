<template>
  <section class="diagnostics" aria-labelledby="diagnostics-heading">
    <div class="section-heading"><h3 id="diagnostics-heading">性能诊断</h3><p>区分连接慢、事务等待与任务启动慢；后台每 30 秒更新，离开此分栏或隐藏页面后暂停。</p></div>
    <p class="muted">耗时窗口：最近 {{ Math.round((performance.window_seconds || 900)/60) }} 分钟 · {{ performance.sources?.length || 0 }} 个进程有采样 · 每项每进程最多 {{ performance.per_process_limit || 512 }} 次</p>
    <p v-if="incomplete" class="inline-alert warning" role="status">部分采样不可用或达到容量上限，当前数据可能不完整。请检查共享数据目录的权限与空间。</p>
    <div class="diagnostic-grid">
      <div v-for="item in cards" :key="item.name" class="mini-stat"><span>{{ item.label }} · P95</span><strong>{{ duration(metrics[item.name]?.p95_ms) }}</strong><small>{{ metrics[item.name]?.samples || 0 }} 次采样</small></div>
      <div class="mini-stat"><span>近 24 小时执行失败率</span><strong>{{ health.failure_rate == null ? '暂无执行' : health.failure_rate+'%' }}</strong><small>{{ health.failures || 0 }} 次失败 / {{ health.attempts || 0 }} 次完成</small></div>
    </div>
    <p class="diagnostic-note">失败率 =（失败 + 超时）÷（成功 + 失败 + 超时）。取消、中断、跳过、错过和未知结果单列，不计入分母；试运行不计入。统计截至 {{ health.to?.split('.')[0] || '—' }}，最多缓存 30 秒。</p>
    <div class="runtime-alerts"><span v-for="item in excluded" :key="item.name" class="tag info">{{ item.label }} {{ health.counts?.[item.name] || 0 }}</span></div>
    <details class="disclosure"><summary>查看全部耗时与采样来源</summary><div class="disclosure-body">
      <p class="diagnostic-note">P95 表示 95% 的样本不超过该耗时。队列等待从请求创建到成功派发（含计划延后和重试退避）；启动延迟从计划时间或创建时间到进程启动，两者可能重叠，不能相加。</p>
      <div class="table-wrap"><table class="runtime-metrics"><thead><tr><th>操作</th><th>样本数</th><th>P50</th><th>P95</th><th>最大耗时</th></tr></thead><tbody><tr v-for="(metric,name) in metrics" :key="name"><td>{{ label(name) }}<small v-if="label(name)!==name" class="metric-key mono">{{ name }}</small></td><td>{{ metric.samples }}</td><td>{{ duration(metric.p50_ms) }}</td><td>{{ duration(metric.p95_ms) }}</td><td>{{ duration(metric.max_ms) }}</td></tr></tbody></table><p v-if="!Object.keys(metrics).length" class="table-empty-note">暂无采样；访问页面或运行任务后会逐步产生数据。</p></div>
      <p class="diagnostic-note">Web 与调度器通过共享数据目录汇总，其他进程约每 {{ performance.flush_seconds || 5 }} 秒写入一次；这里展示有界采样，不是完整历史监控。停机进程在窗口内的样本仍保留。</p>
      <div class="runtime-alerts"><span v-for="source in performance.sources || []" :key="source.id || source.pid" class="tag info">{{ source.role }} · PID {{ source.pid }} · {{ source.age_seconds }} 秒前</span></div>
    </div></details>
  </section>
</template>
<script setup>
import {computed} from 'vue';
const props=defineProps({runtime:{type:Object,default:()=>({})}});
const performance=computed(()=>props.runtime.performance || {});
const metrics=computed(()=>performance.value.metrics || props.runtime.metrics || {});
const health=computed(()=>props.runtime.execution_health || {});
const incomplete=computed(()=>performance.value.write_error || performance.value.invalid_snapshots || performance.value.truncated || performance.value.dropped_metrics);
const cards=[{name:'database:connect',label:'平台数据库连接'},{name:'lock:all',label:'事务锁等待'},{name:'queue:dispatch_wait',label:'队列等待'},{name:'task:start_delay',label:'任务启动延迟'}];
const excluded=[{name:'cancelled',label:'取消'},{name:'interrupted',label:'中断'},{name:'skipped',label:'跳过'},{name:'missed',label:'错过'},{name:'unknown',label:'未知'}];
const names={'lock:all':'事务锁等待（全部分区）','database:connect':'平台数据库连接','database:config':'数据库配置读取','database:query':'数据库查询','database:write':'数据库写入','queue:dispatch_wait':'请求队列等待','task:start_delay':'任务启动延迟'};
const label=name=>names[name] || (name.startsWith('lock:')?'事务锁等待 · '+name.slice(5):name.startsWith('nacos:')?'Nacos · '+name.slice(6):name);
const duration=value=>value==null?'待采样':value>=1000?(value/1000).toFixed(2)+' s':Number(value).toFixed(1)+' ms';
</script>
<style scoped>
.diagnostics{margin-top:24px;border-top:1px solid var(--line);padding-top:20px}.diagnostic-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.diagnostic-grid strong{font-size:24px}.diagnostic-grid small,.diagnostic-note,.metric-key{color:var(--muted);font-size:12px;line-height:1.7}.metric-key{display:block;overflow-wrap:anywhere}.diagnostic-note{margin:14px 0}.diagnostics .runtime-alerts{display:flex;flex-wrap:wrap;gap:8px}.diagnostics .disclosure{margin-top:16px}
</style>
