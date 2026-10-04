<template>
  <section class="task-flow-viewer" aria-label="任务执行流程">
    <div class="flow-toolbar">
      <div><strong>执行流程概览</strong><p class="hint">从入口与本地模块自动提取 · 分析时不会运行任务</p></div>
      <button class="btn" :disabled="loading" @click="load">{{ loading ? '分析中…' : '重新分析' }}</button>
    </div>
    <div v-if="error" class="inline-alert danger" role="alert">{{ error }}</div>
    <template v-if="data">
      <p class="hint flow-version">入口 {{ data.entry }} · {{ data.files.length }} 个文件 · {{ data.graphs.length }} 个模块/函数 · {{ data.code_version ? `代码版本 ${data.code_version.slice(0,8)}` : `代码校验 ${data.fingerprint.slice(0,8)}` }}</p>
      <div class="flow-controls">
        <label>查看流程<select v-model="graphId" class="input" aria-label="查看流程"><option v-for="item in data.graphs" :key="item.id" :value="item.id">{{ item.title }} · {{ item.file }}</option></select></label>
        <div class="filter-actions"><button class="btn" :disabled="!history.length" @click="back">返回上层</button><button class="btn" @click="entry">入口流程</button><button class="btn" aria-label="缩小流程图" :disabled="zoom <= .35" @click="zoomBy(-.15)">−</button><span class="mono">{{ Math.round(zoom*100) }}%</span><button class="btn" aria-label="放大流程图" :disabled="zoom >= 1.8" @click="zoomBy(.15)">＋</button><button class="btn" @click="fit">适应宽度</button></div>
      </div>
      <p v-if="data.business_summary" class="flow-summary">{{ data.business_summary }}</p>
      <p v-if="graph?.summary" class="flow-summary">{{ graph.summary }}</p>
      <div class="flow-workspace">
        <div ref="canvas" class="flow-canvas" aria-label="流程图，可拖动空白区域和使用缩放按钮" @pointerdown="startPan" @pointermove="pan" @pointerup="stopPan" @pointercancel="stopPan">
          <svg :viewBox="`0 0 ${layout.width} ${layout.height}`" :style="{width:`${layout.width*zoom}px`,height:`${layout.height*zoom}px`}" role="group" :aria-label="graph?.title">
            <defs><marker :id="arrowId" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" /></marker></defs>
            <g v-for="(edge,index) in layout.edges" :key="index" class="flow-edge" :class="edge.kind"><path :d="edge.path" :marker-end="`url(#${arrowId})`" /><text v-if="edge.label" :x="edge.labelX" :y="edge.labelY">{{ edge.label }}</text></g>
            <g v-for="node in layout.nodes" :key="node.id" class="flow-node" :class="[node.kind,{selected:selectedId === node.id}]" :transform="`translate(${node.x},${node.y})`" role="button" tabindex="0" :aria-label="`${node.label}，${node.file}第${node.line}行`" @click="selectedId = node.id" @keydown.enter.prevent="selectedId = node.id" @keydown.space.prevent="selectedId = node.id">
              <rect x="-116" y="-36" width="232" height="72" :rx="['start','end'].includes(node.kind) ? 36 : 14" />
              <text v-for="(line,index) in flowLabelLines(node.label)" :key="index" text-anchor="middle" :y="(index-(flowLabelLines(node.label).length-1)/2)*17+5">{{ line }}</text>
              <circle v-if="node.calls.some(call => call.target)" cx="103" cy="-25" r="4" class="flow-expand-dot" />
            </g>
          </svg>
        </div>
        <aside class="flow-inspector" aria-label="流程步骤详情">
          <template v-if="selected">
            <span class="tag info">{{ kindLabel(selected.kind) }}</span><h4>{{ selected.label }}</h4>
            <p v-if="selected.description">{{ selected.description }}</p><p class="mono">{{ selected.file }} : {{ selected.line }}</p>
            <button class="btn" @click="showSource">查看对应代码</button>
            <template v-if="selected.calls.length"><h4>此步骤中的调用</h4><div v-for="(call,index) in selected.calls" :key="index" class="flow-call"><strong class="mono">{{ call.name }}</strong><small v-if="call.target === graphId" class="hint">递归调用当前函数，可复用当前流程。</small><button v-else-if="call.target" class="btn" @click="expand(call.target)">展开函数流程</button><small v-else class="hint">未展开调用，请结合源码查看。</small></div><p v-if="selected.calls.length > 1" class="hint">调用列表用于定位；复杂表达式的求值顺序请查看源码。</p></template>
          </template>
          <template v-else><h4>阅读流程</h4><p>沿箭头查看执行步骤。判断节点展示分支，虚线表示循环或可能的异常路径。</p><p>点击节点查看源码位置；带小圆点的步骤可展开本地函数。</p></template>
        </aside>
      </div>
      <details class="flow-notes"><summary>分析范围与说明{{ data.warnings.length ? ` · ${data.warnings.length} 项提示` : '' }}</summary><p v-for="note in [...data.limitations,...data.warnings]" :key="note" class="hint">{{ note }}</p></details>
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue';
import { api } from '../api';
import { layoutFlow, flowLabelLines } from '../taskFlowLayout';
const props = defineProps({pid:{type:String,required:true},revision:{type:Number,default:0}});
const emit=defineEmits(['source','loading']);
const data=ref(null),error=ref(''),loading=ref(false),graphId=ref(''),selectedId=ref(''),zoom=ref(1),canvas=ref(null),history=ref([]);
const arrowId='flow-arrow-'+useId().replace(/[^a-zA-Z0-9_-]/g,'');
const graph=computed(()=>data.value?.graphs.find(item=>item.id===graphId.value));
const layout=computed(()=>layoutFlow(graph.value));
const selected=computed(()=>graph.value?.nodes.find(node=>node.id===selectedId.value));
let generation=0,stopped=false,drag=null,observer,manualZoom=false;
watch(loading,value=>emit('loading',value));
function kindLabel(kind) { return ({start:'开始',end:'结束',decision:'条件判断',loop:'循环',try:'异常处理',exception:'异常分支',finally:'最终清理',import:'加载模块',call:'函数调用',read:'读取数据',write:'写入数据',database:'数据库',notify:'通知',external:'外部调用',return:'返回',raise:'抛出异常'})[kind] || '执行步骤'; }
function showSource() {
  if (!selected.value) return;
  const {file,line}=selected.value;
  emit('source',{file,line,sha256:data.value.files.find(item=>item.path===file)?.sha256 || ''});
}
async function load() {
  const seq=++generation;loading.value=true;error.value='';
  try { const result=await api.taskFlow(props.pid);if(seq!==generation || stopped)return;data.value=result;if(!result.graphs.some(item=>item.id===graphId.value)){graphId.value=result.graphs[0]?.id || '';history.value=[];}selectedId.value='';await fit(); }
  catch(err) { if(seq===generation && !stopped)error.value=err.message; }
  finally { if(seq===generation && !stopped)loading.value=false; }
}
async function fit() { await nextTick();if(canvas.value && canvas.value.clientWidth>0){manualZoom=false;zoom.value=Math.min(1,Math.max(.35,(canvas.value.clientWidth-24)/layout.value.width));canvas.value.scrollTop=0;canvas.value.scrollLeft=0;} }
function zoomBy(step) { manualZoom=true;zoom.value=Math.max(.35,Math.min(1.8,zoom.value+step)); }
function expand(id) { if(id===graphId.value)return;history.value.push(graphId.value);if(history.value.length>30)history.value.shift();graphId.value=id; }
function back() { graphId.value=history.value.pop(); }
function entry() { history.value=[];graphId.value=data.value.graphs[0].id; }
function startPan(event) { if(event.button!==0 || event.target.closest('.flow-node'))return;drag={x:event.clientX,y:event.clientY,left:canvas.value.scrollLeft,top:canvas.value.scrollTop};canvas.value.setPointerCapture(event.pointerId); }
function pan(event) { if(drag){canvas.value.scrollLeft=drag.left+drag.x-event.clientX;canvas.value.scrollTop=drag.top+drag.y-event.clientY;} }
function stopPan() { drag=null; }
watch(graphId,()=>{selectedId.value='';fit();});
watch(()=>[props.pid,props.revision],()=>{data.value=null;graphId.value='';history.value=[];load();},{immediate:true});
onMounted(()=>{observer=new ResizeObserver(()=>{if(!manualZoom && canvas.value && canvas.value.clientWidth>0)fit();});if(canvas.value)observer.observe(canvas.value);});
watch(canvas,element=>{observer?.disconnect();if(element)observer?.observe(element);});
onBeforeUnmount(()=>{stopped=true;generation++;observer?.disconnect();});
</script>

<style scoped>
.flow-toolbar,.flow-controls { display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap; }
.flow-toolbar .hint { margin:6px 0; }
.flow-version { overflow-wrap:anywhere;margin:8px 0; }
.flow-controls { margin:10px 0; }
.flow-summary { margin:8px 0; }
.flow-controls label { display:flex;gap:8px;align-items:center;flex:1 1 280px; }
.flow-controls select { min-width:0;max-width:360px;flex:1; }
.flow-workspace { display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:16px; }
.flow-canvas { height:clamp(260px,calc(100vh - 460px),520px);overflow:auto;border:1px solid var(--line);border-radius:var(--surface-glass-radius);background:radial-gradient(circle,var(--line) 1px,transparent 1px) 0 0/20px 20px,var(--panel-soft);touch-action:none;cursor:grab; }
.flow-canvas:active { cursor:grabbing; }
.flow-canvas svg { display:block;min-width:0;max-width:none;color:var(--muted); }
.flow-node { cursor:pointer;outline:none; }
.flow-node rect { fill:var(--panel);stroke:var(--line-strong);stroke-width:1.5; }
.flow-node text { fill:var(--ink);font-size:13px;user-select:none; }
.flow-node.start rect,.flow-node.end rect { fill:var(--brand-soft);stroke:var(--brand); }
.flow-node.decision rect,.flow-node.loop rect { fill:var(--warning-soft);stroke:var(--warning); }
.flow-node.exception rect,.flow-node.raise rect { fill:var(--danger-soft);stroke:var(--danger); }
.flow-node:hover rect,.flow-node:focus rect,.flow-node.selected rect { stroke:var(--brand);stroke-width:3; }
.flow-expand-dot { fill:var(--brand); }
.flow-edge path { fill:none;stroke:var(--muted);stroke-width:1.5; }
.flow-edge text { fill:var(--muted-strong);font-size:11px;paint-order:stroke;stroke:var(--panel-soft);stroke-width:4;stroke-linejoin:round; }
.flow-edge.loop path,.flow-edge.exception path { stroke-dasharray:6 4; }
.flow-edge.exception path { stroke:var(--danger); }
.flow-inspector { min-width:0;border:1px solid var(--line);border-radius:14px;padding:16px;background:var(--panel);overflow-wrap:anywhere; }
.flow-inspector h4 { margin:12px 0; }
.flow-inspector p { font-size:13px;line-height:1.8; }
.flow-call { display:grid;gap:8px;border-top:1px solid var(--line);padding:12px 0; }
.flow-call .btn { justify-self:start; }
.flow-notes { margin-top:16px;padding:12px 16px;border:1px solid var(--line);border-radius:12px; }
.flow-notes summary { cursor:pointer;font-size:13px; }
.flow-notes p { margin:10px 0 0; }
@media(max-width:900px) { .flow-workspace { grid-template-columns:minmax(0,1fr); }.flow-canvas { height:460px; }.flow-inspector { min-height:130px; } }
</style>
