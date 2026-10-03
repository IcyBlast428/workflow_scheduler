<template>
  <div class="loading-status" :class="{ 'is-loading': visible }" :aria-busy="active">
    <div class="loading-status-content" :aria-hidden="!visible">
      <span role="status" aria-live="polite">{{ visible ? label : '' }}</span>
      <div class="loading-bar" aria-hidden="true"></div>
    </div>
  </div>
</template>
<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
const props = defineProps({ active: Boolean, label: { type: String, default: '正在更新…' } });
const visible = ref(false);
let timer;
watch(() => props.active, active => {
  clearTimeout(timer);
  visible.value = false;
  if (active) timer = setTimeout(() => { visible.value = true; }, 180);
}, { immediate: true });
onBeforeUnmount(() => clearTimeout(timer));
</script>
