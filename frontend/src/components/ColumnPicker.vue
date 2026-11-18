<template>
  <details class="column-picker" ref="picker" @keydown.esc.stop.prevent="close">
    <summary ref="trigger">显示列</summary>
    <div class="column-options" role="group" aria-label="显示列">
      <label v-for="option in options" :key="option.key">
        <input
          type="checkbox"
          :checked="modelValue.includes(option.key)"
          @change="toggle(option.key, $event.target.checked)"
        >
        {{ option.label }}
      </label>
    </div>
  </details>
</template>

<script setup>
import { ref } from 'vue';

const props = defineProps({
  modelValue: { type: Array, required: true },
  options: { type: Array, required: true },
});
const emit = defineEmits(['update:modelValue']);
const picker = ref(null);
const trigger = ref(null);

function toggle(key, checked) {
  const selection = new Set(props.modelValue);
  if (checked) selection.add(key);
  else selection.delete(key);
  emit('update:modelValue', [...selection]);
}

function close() {
  if (!picker.value.open) return;
  picker.value.open = false;
  trigger.value.focus({ preventScroll: true });
}
</script>

<style scoped>
.column-picker { position: relative; font-size: 13px; }
.column-picker summary { cursor: pointer; padding: 8px; }
.column-options {
  position: absolute;
  z-index: 5;
  inset-block-start: 100%;
  inset-inline-start: 0;
  display: grid;
  gap: 12px;
  min-width: 200px;
  max-width: calc(100vw - 32px);
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  box-shadow: var(--shadow);
}
.column-options label { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
</style>
