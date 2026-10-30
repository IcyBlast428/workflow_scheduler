<template>
<section class="task-operations" aria-label="任务运行策略">
<h3>运行策略</h3><p class="hint">重试与补跑默认关闭。参数供任务从运行环境读取，请勿在参数中填写密码或令牌。</p>
<p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p><p v-if="message" role="status">{{ message }}</p>
<form @submit.prevent="save"><fieldset :disabled="busy || !loaded">
<label class="checkbox-row"><input v-model="form.idempotent" type="checkbox">已核实此任务可安全重复执行</label>
<label class="checkbox-row"><input v-model="form.retry_enabled" type="checkbox" :disabled="!form.idempotent">脚本失败后自动重试（超时、取消和中断不自动重试）</label>
<div class="filter-grid"><label>最多重试次数<input v-model.number="form.retry_limit" class="input" type="number" min="0" max="3"></label><label>首次重试等待（秒）<input v-model.number="form.retry_delay" class="input" type="number" min="10" max="86400"></label><label>每日期望完成时间<input v-model="form.expected_by" class="input" type="time"></label><label>长时间运行提醒（分钟）<input v-model.number="form.slow_minutes" class="input" type="number" min="1" max="10080"></label></div>
<label>允许错峰的最大延迟（秒）<input v-model.number="form.stagger_seconds" class="input" type="number" min="0" max="300"></label><p class="hint">0 表示不主动错峰。大于 0 时按任务标识固定偏移；原计划时间保留，排队与错峰合计不能超过允许迟到窗口。需要准点触发的任务请保持 0。</p>
<label>默认运行参数（JSON 对象）<textarea v-model="parameters" class="input mono" rows="4" spellcheck="false" /></label>
<label>声明使用的业务连接（每行一个标识）<textarea v-model="declared" class="input" rows="3" /></label>
<label>试运行连接替换（每行 原标识=测试标识）<textarea v-model="mapping" class="input" rows="3" placeholder="orders=orders_test" /></label>
<p class="hint">试运行不替换当前发布版本、调度策略或正式任务数据，只提供上述测试连接。脚本仍须避免自行连接生产系统或产生外部副作用。</p>
<label>执行隔离<select v-model="form.isolation" class="select"><option value="process">普通进程（可信脚本）</option><option value="systemd">systemd 隔离与资源限制（Linux）</option></select></label>
<div v-if="form.isolation === 'systemd' && form.resources" class="filter-grid"><label>整组内存上限（MiB）<input v-model.number="form.resources.memory_mb" class="input" type="number" min="64" max="32768"></label><label>整组进程与线程上限<input v-model.number="form.resources.processes" class="input" type="number" min="1" max="1024"></label><label>CPU 配额（100% 为一个核心）<input v-model.number="form.resources.cpu_percent" class="input" type="number" min="1" max="1600"></label></div>
<p class="hint">systemd 模式要求已冻结公共 SDK 的版本及指定连接授权；无法建立隔离时拒绝启动，不自动降级。</p>
<div class="filter-actions"><button class="btn" type="button" @click="probe">检测隔离能力</button><button class="btn primary" type="submit">保存运行策略</button></div><p v-if="probeResult" class="hint">{{ probeResult.message }}</p>
</fieldset></form>
<details v-if="published" class="disclosure"><summary>参数化运行与按业务日期补跑</summary><div class="disclosure-body"><div class="operational-stack"><label>业务日期<input v-model="businessDate" class="input" type="date"></label><p class="hint">补跑使用当前已发布版本；提交前核对业务数据。默认参数沿用上方保存值。</p><div class="filter-actions"><button class="btn" :disabled="busy || !form.idempotent || !businessDate" @click="submit('backfill')">提交补跑请求</button><button class="btn" :disabled="busy" @click="submit('manual')">带参数执行一次</button></div></div></div></details>
<div class="filter-actions"><h4>执行请求</h4><button class="btn" :disabled="busy" @click="loadRequests">刷新请求</button></div>
<div class="table-wrap"><table><thead><tr><th>类型</th><th>状态</th><th>时间</th><th>结果</th></tr></thead><tbody><tr v-for="item in requests" :key="item.id"><td>{{ kinds[item.kind] }}</td><td>{{ statuses[item.status] || item.status }}</td><td>{{ item.due_at }}</td><td>{{ item.message }}<button v-if="item.status === 'pending'" class="btn" :disabled="busy" @click="cancelRequest(item)">取消待派发请求</button><button v-if="item.run_id" class="btn" @click="$emit('execution',item.run_id)">查看执行</button></td></tr></tbody></table></div>
</section>
</template>
<script setup>
import { ref,watch,onBeforeUnmount } from 'vue';import { api } from '../api';
import {useUnsavedChanges} from '../composables/useUnsavedChanges';
const props=defineProps({pid:String,confirm:Function,published:{type:Boolean,default:true}});defineEmits(['execution']);
const form=ref({}),parameters=ref('{}'),declared=ref(''),mapping=ref(''),businessDate=ref(''),error=ref(''),message=ref(''),busy=ref(false),loaded=ref(false),requests=ref([]),probeResult=ref(null);
const {saved:policySaved}=useUnsavedChanges(()=>({form:form.value,parameters:parameters.value,declared:declared.value,mapping:mapping.value}),()=>loaded.value);
const kinds={scheduled:'自动计划',trial:'试运行',retry:'自动重试',backfill:'业务补跑',manual:'参数化执行'},statuses={expired:'等待超时',rejected:'未接收',pending:'待派发',dispatching:'派发中',accepted:'已接收',unknown:'待人工核对',cancelled:'已取消'};let generation=0;
async function loadRequests(){try{requests.value=await api.executionRequests(props.pid);}catch(e){error.value=e.message;}}
watch(()=>props.pid,async pid=>{const seq=++generation;loaded.value=false;error.value='';try{const data=await api.operationalPolicy('task',pid);if(seq!==generation)return;form.value=data;parameters.value=JSON.stringify(data.parameters,null,2);declared.value=data.declared_connections.join('\n');mapping.value=Object.entries(data.test_connections).map(([a,b])=>a+'='+b).join('\n');loaded.value=true;policySaved();await loadRequests();}catch(e){if(seq===generation)error.value=e.message;}},{immediate:true});
async function save(){if(busy.value)return;busy.value=true;try{const connections=Object.fromEntries(mapping.value.split(/\r?\n/).filter(s=>s.trim()).map(s=>{const parts=s.split('=');if(parts.length!==2)throw new Error('测试连接请使用 原标识=测试标识。');return parts.map(v=>v.trim());}));form.value=await api.saveOperationalPolicy('task',{...form.value,parameters:JSON.parse(parameters.value),declared_connections:declared.value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean),test_connections:connections},props.pid);policySaved();message.value='运行策略已保存，下次执行生效。';error.value='';}catch(e){error.value=e.message;}finally{busy.value=false;}}
async function submit(kind){if(!await props.confirm({title:kind==='backfill'?'按业务日期补跑':'带参数执行',message:kind==='backfill'?`使用当前发布版本补跑 ${businessDate.value}。`:'使用当前发布版本和本次输入的参数执行。',details:['这会执行业务脚本，请确认参数、目标连接及业务幂等规则。'],confirmText:'提交执行请求',danger:true}))return;busy.value=true;try{await api.submitExecutionRequest(props.pid,{kind,request_id:crypto.randomUUID().replaceAll('-',''),context:{business_date:businessDate.value,parameters:JSON.parse(parameters.value)}});message.value='执行请求已保存。';await loadRequests();}catch(e){error.value=e.message;}finally{busy.value=false;}}
async function cancelRequest(item){if(!await props.confirm({title:'取消待派发请求',message:'只取消此请求，不停止已开始的执行。',confirmText:'取消此请求',danger:true}))return;busy.value=true;try{await api.cancelExecutionRequest(item.id);await loadRequests();}catch(e){error.value=e.message;}finally{busy.value=false;}}
async function probe(){try{probeResult.value=await api.isolationProbe();}catch(e){error.value=e.message;}}
onBeforeUnmount(()=>generation++);
</script>
<style scoped>.task-operations,.task-operations fieldset,.operational-stack{display:grid;gap:16px}.task-operations fieldset{border:0;padding:0;margin:0;min-width:0}.task-operations label{display:grid;gap:8px}.task-operations .checkbox-row{display:flex}.task-operations .filter-grid{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}</style>
