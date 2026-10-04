<template>
  <div v-if="open" ref="backdrop" class="modal-backdrop" :class="backdropClass" @click.self="$emit('close')">
    <section ref="panel" v-glass class="modal glass-surface glass-floating" :class="panelClass" role="dialog" aria-modal="true" :aria-label="label" tabindex="-1">
      <slot />
    </section>
  </div>
</template>
<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { dialogStack, enterDialog, leaveDialog } from '../dialogStack';
const props = defineProps({ open: Boolean, label: { type: String, required: true }, panelClass: String, backdropClass: String });
const emit = defineEmits(['close']);
const backdrop = ref(null), panel = ref(null);
let previousFocus, openedElement;
function isolate() {
  if (!backdrop.value) return;
  backdrop.value.style.zIndex = String(100 + dialogStack.indexOf(backdrop.value) * 10);
}
function focusable() {
  return [...panel.value.querySelectorAll('button, a[href], input, select, textarea, [tabindex]')]
    .filter(el => !el.disabled && el.tabIndex >= 0 && !el.closest('[inert]') && el.getClientRects().length);
}
function keydown(event) {
  if (dialogStack.at(-1) !== backdrop.value) return;
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); emit('close'); }
  if (event.key !== 'Tab') return;
  const items = focusable(), first = items[0], last = items.at(-1);
  if (!first) { event.preventDefault(); panel.value.focus(); }
  else if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value || !panel.value.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (document.activeElement === last || !panel.value.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
}
function cleanup() {
  document.removeEventListener('keydown', keydown, true);
  document.removeEventListener('wfs:dialogs', isolate);
  if (openedElement) { leaveDialog(openedElement); openedElement = null; }
  nextTick(() => { if (previousFocus?.isConnected && !previousFocus.closest('[inert]')) previousFocus.focus(); });
}
watch(() => props.open, async open => {
  if (typeof document === 'undefined') return;
  if (!open) { cleanup(); return; }
  previousFocus = document.activeElement;
  await nextTick();
  if (!props.open || !panel.value) return;
  openedElement = backdrop.value; enterDialog(openedElement); document.addEventListener('wfs:dialogs', isolate);
  isolate();
  document.addEventListener('keydown', keydown, true);
  panel.value.focus();
}, { immediate: true });
onBeforeUnmount(cleanup);
</script>
