<template>
  <div v-if="modelValue.open" class="modal-backdrop confirm-backdrop" @click.self="dismiss">
    <section class="modal confirm-modal">
      <header class="modal-head">
        <div>
          <p class="eyebrow">{{ modelValue.eyebrow || '高风险操作' }}</p>
          <h3>{{ modelValue.title }}</h3>
        </div>
        <button class="btn icon-only" type="button" title="关闭" @click="dismiss">×</button>
      </header>
      <div class="modal-body confirm-body">
        <p>{{ modelValue.message }}</p>
        <ul v-if="modelValue.details?.length" class="confirm-details">
          <li v-for="detail in modelValue.details" :key="detail">{{ detail }}</li>
        </ul>
      </div>
      <footer class="confirm-footer">
        <button v-if="modelValue.cancelText === '仅暂停'" class="btn" type="button" @click="dismiss">取消</button>
        <button class="btn" type="button" @click="cancel">{{ modelValue.cancelText || '取消' }}</button>
        <button class="btn" :class="modelValue.danger ? 'danger' : 'primary'" type="button" @click="confirm">
          {{ modelValue.confirmText || '确认执行' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<script setup>
const props = defineProps({
  modelValue: { type: Object, required: true },
});

const emit = defineEmits(['resolve']);

function cancel() {
  emit('resolve', false);
}

function dismiss() { emit('resolve', null); }

function confirm() {
  emit('resolve', true);
}
</script>
