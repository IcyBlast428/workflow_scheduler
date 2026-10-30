<template>
<section class="panel execution-queue">
  <div class="panel-head"><div><h2>执行队列</h2><p>查看等待原因和执行去向；已派发表示已交给执行器，并不代表执行成功。</p></div><div class="filter-actions"><button class="btn" @click="$emit('settings')">排队策略</button><button class="btn" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新队列' }}</button></div></div>
  <div class="panel-body">
    <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p><p v-if="message" role="status">{{ message }}</p>
    <div class="queue-summary" aria-label="队列概况"><button class="mini-stat" @click="filter('pending')"><span>等待派发</span><strong>{{ state.counts?.pending || 0 }}</strong></button><div class="mini-stat"><span>占用名额 / 上限</span><strong>{{ state.active || 0 }} / {{ state.max_active || '—' }}</strong></div><div class="mini-stat"><span>当前最长等待</span><strong>{{ waiting(state.oldest_wait_seconds) }}</strong></div><button class="mini-stat" @click="filter('expired')"><span>近 24 小时等待超时</span><strong>{{ state.counts?.expired || 0 }}</strong></button></div>
    <div class="queue-health"><span class="tag" :class="state.reason ? 'warning' : 'success'">{{ state.reason || '按名额和启动间隔派发' }}</span><span>CPU {{ percent(state.cpu_percent) }} · 内存 {{ percent(state.memory_percent) }}</span><span class="hint">{{ updated ? '最近更新 '+updated : '正在读取…' }} · 可见时每 5 秒刷新</span></div>
    <form class="queue-filters" @submit.prevent="search"><label>任务名称或 ID<input v-model.trim="query" class="input" maxlength="200" placeholder="查找任务"></label><label>请求状态<select v-model="status" class="select" aria-label="请求状态"><option value="">全部状态</option><option v-for="(label,value) in statuses" :key="value" :value="value">{{ label }}</option></select></label><div class="filter-actions"><button class="btn primary" type="submit">查询</button><button class="btn" type="button" @click="reset">清空筛选</button></div></form>
    <p class="hint">终态请求保留 7 天，待核对请求持续保留。上方异常计数为近 24 小时；下方筛选覆盖全部保留记录。</p>
    <div class="table-wrap"><table class="queue-table"><thead><tr><th>任务 / 类型</th><th>状态</th><th>等待时长 / 最晚启动</th><th>等待原因或结果说明</th><th>操作</th></tr></thead><tbody><tr v-for="item in state.items || []" :key="item.id"><td><button class="task-name-link" @click="$emit('detail',item.pid)">{{ item.task_name }}</button><small class="cell-subtitle mono">{{ item.pid }}</small><small class="cell-subtitle">{{ kinds[item.kind] || item.kind }}</small></td><td><span class="tag" :class="tone(item.status)">{{ statuses[item.status] || item.status }}</span></td><td>{{ item.wait_seconds == null ? '—' : waiting(item.wait_seconds) }}<small class="cell-subtitle">{{ item.expires_at || '旧请求未设期限' }}</small></td><td>{{ item.status==='pending' && state.reason ? state.reason : item.message || '—' }}</td><td><div class="filter-actions"><button v-if="item.status==='pending'" class="btn" :disabled="busy===item.id" @click="cancel(item)">取消请求</button><button v-if="item.run_id" class="btn" @click="$emit('execution',item.run_id)">查看执行</button></div></td></tr></tbody></table></div>
    <p v-if="!loading && !state.items?.length" class="empty-state">{{ applied.query || applied.status ? '没有匹配的请求，可清空筛选重试。' : '暂无执行请求。任务触发后会在这里显示。' }}</p>
    <div class="filter-actions queue-pagination"><span class="hint">共 {{ state.total || 0 }} 条 · 第 {{ state.page || 1 }} / {{ Math.max(1,Math.ceil((state.total || 0)/25)) }} 页</span><button class="btn" :disabled="loading || (state.page || 1)<=1" @click="go(-1)">上一页</button><button class="btn" :disabled="loading || (state.page || 1)*25 >= (state.total || 0)" @click="go(1)">下一页</button></div>
  </div>
</section>
</template>
<script setup>
import { ref,onMounted,onBeforeUnmount } from 'vue';
import { api } from '../api';
const props=defineProps({confirm:Function});defineEmits(['execution','detail','settings']);
const state=ref({}),error=ref(''),message=ref(''),loading=ref(false),busy=ref(''),query=ref(''),status=ref(''),updated=ref('');
const applied=ref({query:'',status:'',page:1});let alive=true,timer,generation=0;
const statuses={pending:'等待派发',dispatching:'派发中',accepted:'已派发',expired:'等待超时',rejected:'未接收',unknown:'待人工核对',cancelled:'已取消'};
const kinds={scheduled:'自动计划',manual:'参数化执行',trial:'试运行',retry:'重试',backfill:'补跑'};
const waiting=value=>value==null?'—':value<60?value+' 秒':Math.floor(value/60)+' 分 '+value%60+' 秒';
const percent=value=>value==null?'待采样':value+'%';
const tone=status=>({pending:'warning',dispatching:'brand',expired:'danger',rejected:'danger',unknown:'warning',accepted:'info',cancelled:'info'})[status];
async function load(){const seq=++generation;loading.value=true;try{const value=await api.dispatchStatus(applied.value);if(!alive || seq!==generation)return;state.value=value;applied.value.page=value.page;error.value='';updated.value=new Date().toLocaleTimeString('zh-CN',{hour12:false});}catch(e){if(alive && seq===generation)error.value=e.message;}finally{if(alive && seq===generation)loading.value=false;}}
function search(){applied.value={query:query.value,status:status.value,page:1};load();}
function filter(value){status.value=value;search();}
function reset(){query.value='';status.value='';search();}
function go(delta){applied.value={...applied.value,page:(state.value.page || 1)+delta};load();}
async function cancel(item){if(!await props.confirm({title:'取消待派发请求',message:'取消 '+item.task_name+' 的这一次请求，不停用调度，也不停止已运行的任务。',confirmText:'取消此请求',danger:true}))return;busy.value=item.id;try{await api.cancelExecutionRequest(item.id);message.value='请求已取消。';await load();}catch(e){error.value=e.message;}finally{busy.value='';}}
onMounted(()=>{load();timer=setInterval(()=>{if(!document.hidden && !loading.value && !busy.value)load();},5000);});onBeforeUnmount(()=>{alive=false;generation++;clearInterval(timer);});
</script>
<style scoped>
.execution-queue p{margin:0}.queue-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.queue-summary button{text-align:left;font:inherit;color:inherit;cursor:pointer}.queue-summary strong{font-size:23px}.queue-health{display:flex;gap:12px;flex-wrap:wrap;align-items:center;font-size:13px}.queue-filters{display:grid;grid-template-columns:minmax(180px,1fr) minmax(160px,.6fr) auto;gap:16px;align-items:end}.queue-filters label{display:grid;gap:8px}.queue-table{min-width:850px}.queue-table td{max-width:300px;overflow-wrap:anywhere}.queue-table .filter-actions{flex-wrap:wrap}.queue-pagination{justify-content:flex-end}.queue-pagination>span{margin-right:auto}@media(max-width:760px){.queue-summary{grid-template-columns:1fr 1fr}.queue-filters{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.queue-filters>.filter-actions{grid-column:1/-1}.queue-summary strong{font-size:20px}}
</style>
