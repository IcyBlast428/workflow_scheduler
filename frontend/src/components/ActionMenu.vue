<template>
  <button ref="anchor" class="btn" type="button" aria-haspopup="true" :aria-expanded="open" @click="toggle" @keydown.down.prevent="show">更多</button>
  <Teleport to="body">
    <div v-if="open" ref="menu" class="action-menu glass-surface" :style="position" aria-label="任务更多操作" @click.capture="restoreAnchor" @click="close" @keydown.esc.prevent.stop="close" @keydown="navigate"><slot /></div>
  </Teleport>
</template>
<script setup>
import { nextTick, onBeforeUnmount, ref } from 'vue';
const anchor = ref(null), menu = ref(null), open = ref(false), position = ref({});
function buttons() { return [...menu.value.querySelectorAll('button')].filter(el => !el.disabled); }
function restoreAnchor(event) { if (!event.target.closest('button:disabled')) anchor.value?.focus(); }
async function show() {
  open.value = true; await nextTick();
  const rect = anchor.value.getBoundingClientRect();
  const height = menu.value.offsetHeight;
  position.value = { left: `${Math.max(8,Math.min(rect.right-180,innerWidth-188))}px`, top: `${Math.max(8, rect.bottom+height+12 > innerHeight ? rect.top-height-6 : rect.bottom+6)}px` };
  buttons()[0]?.focus();
  document.addEventListener('pointerdown', outside, true); window.addEventListener('scroll', close, true); window.addEventListener('resize', close);
}
function close(event) {
  if (event?.target?.closest('button:disabled')) return;
  open.value = false; document.removeEventListener('pointerdown', outside, true); window.removeEventListener('scroll', close, true); window.removeEventListener('resize', close);
  if (!event || ['keydown','click'].includes(event.type)) anchor.value?.focus();
}
function toggle() { if (open.value) close(); else show(); }
function outside(event) { if (!menu.value?.contains(event.target) && !anchor.value?.contains(event.target)) close(event); }
function navigate(event) {
  if (!['ArrowDown','ArrowUp','Home','End','Tab'].includes(event.key)) return;
  const items = buttons(); if (!items.length) return;
  if (event.key === 'Tab') { close(); return; }
  event.preventDefault(); const index = items.indexOf(document.activeElement);
  const target = event.key === 'Home' ? 0 : event.key === 'End' ? items.length-1 : (index + (event.key === 'ArrowDown' ? 1 : -1)+items.length)%items.length;
  items[target].focus();
}
onBeforeUnmount(() => close({type:'unmount'}));
</script>
