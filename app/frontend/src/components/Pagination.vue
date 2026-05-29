<template>
  <div class="pagination">
    <span class="muted">Total {{ total }}, page {{ page }} / {{ totalPages }}</span>
    <div class="pagination-controls">
      <select class="select compact" :value="pageSize" @change="emitPageSize">
        <option v-for="size in pageSizes" :key="size" :value="size">{{ size }} / page</option>
      </select>
      <button class="btn" type="button" :disabled="page <= 1" @click="$emit('page', page - 1)">Prev</button>
      <button class="btn" type="button" :disabled="page >= totalPages" @click="$emit('page', page + 1)">Next</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  page: { type: Number, required: true },
  pageSize: { type: Number, required: true },
  total: { type: Number, required: true },
});

const emit = defineEmits(['page', 'page-size']);
const pageSizes = [10, 20, 50, 100];
const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));

function emitPageSize(event) {
  emit('page-size', Number(event.target.value));
}
</script>
