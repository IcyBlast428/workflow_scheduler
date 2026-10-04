<template>
  <section class="surface-card heatmap-panel" aria-label="任务执行二维热力图">
    <div class="section-heading"><h3>按小时查看执行分布</h3><p>一行一个任务，一列一个小时。异常优先显示；点击单元格查看该小时的代表记录。业务时区 UTC+8。</p></div>
    <div class="runtime-alerts"><span class="tag success">成功</span><span class="tag warning">执行中 / 等待</span><span class="tag danger">异常</span><span class="tag info">取消</span></div>
    <div class="table-wrap heatmap-table"><table><thead><tr><th>任务</th><th v-for="hour in 24" :key="hour">{{ String(hour-1).padStart(2,'0') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.task.pid"><th><button class="task-name-link" @click="$emit('task',row.task.pid)">{{ row.task.name }}</button><small class="cell-subtitle">{{ row.task.group }}</small></th><td v-for="(cell,hour) in row.cells" :key="hour"><button class="heatmap-cell" :data-status="cell?.status || 'empty'" :disabled="!cell" :aria-label="`${row.task.name}，${hour} 点，${cell ? `${cell.count} 条记录，${labels[cell.status]}` : '无记录'}`" :title="cell ? `${cell.count} 条 · ${labels[cell.status]}` : '无记录'" @click="$emit('select',cell.record)">{{ cell?.count > 1 ? cell.count : cell ? '•' : '' }}</button></td></tr></tbody></table></div>
    <p v-if="!data.records.length && !data.active.length" class="hint">当天暂无执行记录，可以从任务列表配置调度。</p>
    <button v-if="data.tasks.length > limit" class="btn" @click="limit += 50">再显示 50 个任务</button>
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue'; import { heatmapRows } from '../heatmapData';
const props = defineProps({data:{type:Object,required:true}}); defineEmits(['select','task']);
const limit = ref(50), rows = computed(() => heatmapRows(props.data,limit.value));
const labels = {success:'成功',failed:'异常',running:'执行中或等待',cancelled:'已取消'};
watch(() => props.data.date,() => limit.value = 50);
</script>
