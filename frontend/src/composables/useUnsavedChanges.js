import { computed, onBeforeUnmount, ref } from 'vue';
const editors=new Set();let installed=false,pending;
function beforeUnload(event){if([...editors].some(e=>e.dirty.value)){event.preventDefault();event.returnValue='';}}
export function useUnsavedChanges(read,enabled=()=>true){
  const baseline=ref(JSON.stringify(read()));
  const dirty=computed(()=>enabled() && JSON.stringify(read())!==baseline.value);
  const saved=()=>{baseline.value=JSON.stringify(read());};
  const entry={dirty,saved};editors.add(entry);
  if(typeof window!=='undefined'&&!installed){window.addEventListener('beforeunload',beforeUnload);installed=true;}
  onBeforeUnmount(()=>{editors.delete(entry);if(!editors.size&&installed){window.removeEventListener('beforeunload',beforeUnload);installed=false;}});
  return {dirty,saved};
}
export async function confirmUnsaved(confirm){
  if(![...editors].some(e=>e.dirty.value))return true;
  if(pending)return pending;
  pending=confirm({title:'放弃未保存的修改？',message:'当前页面还有未保存的设置。',confirmText:'放弃修改并离开',cancelText:'继续编辑',danger:true});
  try{const accepted=await pending;if(accepted)editors.forEach(e=>e.saved());return accepted;}finally{pending=null;}
}
