<template>
  <div ref="root" class="user-menu" @focusout="onFocusOut" @keydown="onKeydown">
    <button ref="trigger" class="user-chip" type="button" :aria-label="`${name} 账户菜单`" aria-haspopup="menu" :aria-expanded="open" aria-controls="account-menu" @click="toggle">
      <img class="avatar" :src="avatar || '/static/img/head.gif'" alt="">
      <span>{{ name }}</span>
      <svg class="menu-chevron" :class="{ expanded: open }" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 6 4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
    </button>
    <div v-if="open" id="account-menu" class="user-dropdown" role="menu" :aria-label="`${name} 账户操作`">
      <div class="user-dropdown-heading" role="presentation"><strong>{{ name }}</strong><span>当前登录账户</span></div>
      <button ref="logout" class="user-menu-item" type="button" role="menuitem" @click="exit">
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M8 4H4v12h4M8 10h9m-3-3 3 3-3 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg>
        退出登录
      </button>
    </div>
  </div>
</template>
<script setup>
import { nextTick, onMounted, onBeforeUnmount, ref } from 'vue';
defineProps({ name: { type: String, default: 'Admin' }, avatar: String });
const emit = defineEmits(['logout']);
const root = ref(null), trigger = ref(null), logout = ref(null), open = ref(false);
async function toggle() { open.value = !open.value; if (open.value) { await nextTick(); logout.value?.focus(); } }
function close(restoreFocus = false) { open.value = false; if (restoreFocus) trigger.value?.focus(); }
function exit() { close(); emit('logout'); }
function outside(event) { if (!root.value?.contains(event.target)) close(); }
function onFocusOut(event) { if (!root.value?.contains(event.relatedTarget)) close(); }
async function onKeydown(event) {
  if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); close(true); }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault(); open.value = true; await nextTick(); logout.value?.focus();
  }
}
onMounted(() => document.addEventListener('pointerdown', outside));
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside));
</script>
