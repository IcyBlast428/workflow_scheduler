<template>
  <div class="pagination">
    <span class="muted">{{ exact ? `共 ${total} 条，第 ${page} / ${totalPages} 页` : `第 ${page} 页${hasMore ? '，后面还有记录' : '，已到最后一页'}` }}</span>
    <div class="pagination-controls">
      <select class="select compact" :value="pageSize" :disabled="busy" @change="emitPageSize">
        <option v-for="size in pageSizes" :key="size" :value="size">{{ size }} 条 / 页</option>
      </select>
      <button class="btn" type="button" :disabled="busy || page <= 1" @click="$emit('page', page - 1)">上一页</button>
      <button class="btn" type="button" :disabled="busy || (exact ? page >= totalPages : !hasMore)" @click="$emit('page', page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  page: { type: Number, required: true },
  pageSize: { type: Number, required: true },
  total: { type: Number, required: true },
  exact: { type: Boolean, default: true },
  hasMore: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
});

const emit = defineEmits(['page', 'page-size']);
const pageSizes = [10, 20, 50, 100];
const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));

function emitPageSize(event) {
  emit('page-size', Number(event.target.value));
}
</script>
