import { computed, onBeforeUnmount, ref } from 'vue';
// 注册所有仍挂载的编辑器，包含 v-show 隐藏的分栏；离开页面前一次检查全部草稿。
const editors=new Set();let installed=false,pending;
function beforeUnload(event){if([...editors].some(e=>e.dirty.value)){event.preventDefault();event.returnValue='';}}
export function useUnsavedChanges(read,enabled=()=>true){
  const baseline=ref(JSON.stringify(read()));
  const dirty=computed(()=>enabled() && JSON.stringify(read())!==baseline.value);
  // 只有加载或保存成功后才推进基线；保存失败不能把未保存内容误标记为已提交。
  const saved=()=>{baseline.value=JSON.stringify(read());};
  const entry={dirty,saved};editors.add(entry);
  if(typeof window!=='undefined'&&!installed){window.addEventListener('beforeunload',beforeUnload);installed=true;}
  onBeforeUnmount(()=>{editors.delete(entry);if(!editors.size&&installed){window.removeEventListener('beforeunload',beforeUnload);installed=false;}});
  return {dirty,saved};
}
export async function confirmUnsaved(confirm){
  if(![...editors].some(e=>e.dirty.value))return true;
  // 路由与点击事件可能同时触发离开检查，复用同一个确认框，避免重复弹窗。
  if(pending)return pending;
  pending=confirm({title:'放弃未保存的修改？',message:'当前页面还有未保存的设置。',confirmText:'放弃修改并离开',cancelText:'继续编辑',danger:true});
  try{const accepted=await pending;if(accepted)editors.forEach(e=>e.saved());return accepted;}finally{pending=null;}
}
