<template>
  <div ref="root" class="user-menu" :class="{ 'user-menu-sidebar': placement === 'sidebar' }" @focusout="onFocusOut" @keydown="onKeydown">
    <button ref="trigger" class="user-chip" type="button" :title="`${name} 账户菜单`" :aria-label="`${name} 账户菜单`" aria-haspopup="menu" :aria-expanded="open" aria-controls="account-menu" @click="toggle">
      <img v-if="avatar && avatar !== '/static/img/head.gif'" class="avatar" :src="avatar" alt="">
      <svg v-else class="account-icon" viewBox="0 0 32 32" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="28" height="28" rx="10" fill="currentColor" fill-opacity=".08" stroke="currentColor" stroke-opacity=".2" />
        <circle cx="16" cy="11.5" r="4.2" stroke="currentColor" stroke-width="1.7" />
        <path d="M8.5 25v-1.4a7.5 7.5 0 0 1 15 0V25" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
      </svg>
      <span class="user-name">{{ name }}</span>
      <svg class="menu-chevron" :class="{ expanded: open }" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 6 4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
    </button>
    <Teleport to="body">
    <div v-if="open" id="account-menu" ref="dropdown" v-glass class="user-dropdown glass-surface glass-floating" :style="menuPosition" role="menu" :aria-label="`${name} 账户操作`" @focusout="onFocusOut" @keydown="onKeydown">
      <div class="user-dropdown-heading" role="presentation"><strong>{{ name }}</strong><span>当前登录账户</span></div>
      <button ref="logout" class="user-menu-item" type="button" role="menuitem" @click="exit">
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M8 4H4v12h4M8 10h9m-3-3 3 3-3 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg>
        退出登录
      </button>
    </div>
    </Teleport>
  </div>
</template>
<script setup>
import { nextTick, onMounted, onBeforeUnmount, ref } from 'vue';
const props = defineProps({ name: { type: String, default: 'Admin' }, avatar: String, placement: { type: String, default: 'topbar' } });
const emit = defineEmits(['logout']);
const root = ref(null), dropdown = ref(null), trigger = ref(null), logout = ref(null), open = ref(false);
const menuPosition = ref({});
function positionMenu() {
  if (!open.value || !trigger.value) return;
  const anchor = trigger.value.getBoundingClientRect();
  const width = Math.min(208, window.innerWidth - 28);
  const height = dropdown.value?.offsetHeight || 150;
  if (props.placement === 'sidebar' && window.matchMedia('(min-width: 981px)').matches) {
    menuPosition.value = {
      left: `${Math.max(14, Math.min(anchor.right + 12, window.innerWidth - width - 14))}px`,
      top: `${Math.max(14, Math.min(anchor.bottom - height, window.innerHeight - height - 14))}px`,
    };
    return;
  }
  const top = anchor.bottom + 10 + height <= window.innerHeight - 14 ? anchor.bottom + 10 : Math.max(14, anchor.top - height - 10);
  menuPosition.value = { left:`${Math.max(14, Math.min(anchor.right - width, window.innerWidth - width - 14))}px`, top:`${top}px` };
}
async function toggle() { open.value = !open.value; if (open.value) { positionMenu(); await nextTick(); positionMenu(); logout.value?.focus(); } }
function close(restoreFocus = false) { open.value = false; if (restoreFocus) trigger.value?.focus(); }
function exit() { close(); emit('logout'); }
function contains(target) { return root.value?.contains(target) || dropdown.value?.contains(target); }
function outside(event) { if (!contains(event.target)) close(); }
function onFocusOut(event) { if (!contains(event.relatedTarget)) close(); }
async function onKeydown(event) {
  if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); close(true); }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault(); open.value = true; positionMenu(); await nextTick(); positionMenu(); logout.value?.focus();
  }
}
function onScroll(event) { if (!dropdown.value?.contains(event.target)) close(); }
onMounted(() => { document.addEventListener('pointerdown', outside); document.addEventListener('scroll', onScroll, true); window.addEventListener('resize', positionMenu); });
onBeforeUnmount(() => { document.removeEventListener('pointerdown', outside); document.removeEventListener('scroll', onScroll, true); window.removeEventListener('resize', positionMenu); });
</script>
