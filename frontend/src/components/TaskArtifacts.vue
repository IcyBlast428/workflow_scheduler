<template>
  <section class="task-artifacts" aria-label="本次执行输出文件">
    <div class="filter-actions">
      <strong>输出文件</strong>
      <button class="btn" :disabled="loading" @click="load(directory)">
        刷新输出文件
      </button>
      <button
        class="btn"
        :disabled="!directory || loading"
        @click="load(parentDirectory)"
      >
        上级目录
      </button>
      <span class="mono">/{{ directory }}</span>
    </div>
    <p class="hint">
      本次执行独立保存，更新代码不会覆盖。运行中可预览，执行结束后可下载完整文件。
    </p>
    <LoadingStatus
      :active="loading || previewLoading"
      label="正在读取输出文件…"
    />
    <p v-if="error" class="inline-alert danger" role="alert">{{ error }}</p>
    <p v-if="!loading && !error && !entries.length" class="hint">
      此目录还没有输出文件。任务可通过 WFS_OUTPUT_DIR 保存产物。
    </p>
    <p v-if="truncated" class="hint">
      目录文件过多，只展示扫描上限内的文件，请按子目录组织输出。
    </p>
    <div v-if="entries.length" class="table-wrap artifact-table">
      <table>
        <thead>
          <tr>
            <th>文件名称</th>
            <th>大小</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in entries" :key="item.path">
            <td class="mono">
              {{ item.name }}{{ item.type === 'directory' ? '/' : '' }}
            </td>
            <td>
              {{ item.type === 'directory' ? '目录' : sizeText(item.size) }}
            </td>
            <td class="filter-actions">
              <button
                v-if="item.type === 'directory'"
                class="btn"
                :aria-label="`打开目录 ${item.name}`"
                @click="load(item.path)"
              >
                打开
              </button>
              <template v-else>
                <button
                  class="btn"
                  :aria-label="`预览文件 ${item.name}`"
                  @click="inspect(item.path)"
                >
                  预览
                </button>
                <a
                  v-if="final"
                  class="btn"
                  :href="downloadUrl(item.path)"
                  :aria-label="`下载文件 ${item.name}`"
                  download
                  >下载</a
                >
                <span v-else class="hint">等待执行结束</span>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="filter-actions">
      <button
        v-if="offset"
        class="btn"
        :disabled="loading"
        @click="load(directory, Math.max(0, offset - 200))"
      >
        上一页文件</button
      ><button
        v-if="hasMore"
        class="btn"
        :disabled="loading"
        @click="load(directory, offset + 200)"
      >
        下一页文件
      </button>
    </div>
    <section v-if="preview" class="artifact-preview" aria-label="输出文件预览">
      <div class="filter-actions">
        <strong class="mono">{{ preview.path }}</strong
        ><span>{{ sizeText(preview.size) }}</span
        ><button class="btn" @click="closePreview">关闭预览</button>
      </div>
      <p v-if="preview.truncated" class="hint">
        仅展示部分内容：文本最多 256 KiB / 2000 行，表格最多 200 行、50
        列。下载可获取完整文件。
      </p>
      <div v-if="preview.kind === 'csv'" class="table-wrap artifact-csv">
        <table>
          <tbody>
            <tr v-for="(row, index) in preview.rows" :key="index">
              <td v-for="(cell, column) in row" :key="column">{{ cell }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!preview.rows.length" class="hint">空文件</p>
      </div>
      <CodeBlock
        v-else-if="preview.kind === 'text'"
        :code="preview.content || '（空文件）'"
        :language="preview.language"
        label="输出文件文本"
      />
      <p v-else class="hint">{{ preview.reason }}</p>
    </section>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { api } from '../api';
import CodeBlock from './CodeBlock.vue';
import LoadingStatus from './LoadingStatus.vue';
const props = defineProps({
  runId: { type: String, required: true },
  status: String,
});
const entries = ref([]),
  directory = ref(''),
  offset = ref(0),
  hasMore = ref(false),
  truncated = ref(false);
const final = ref(false),
  loading = ref(false),
  previewLoading = ref(false),
  error = ref(''),
  preview = ref(null);
let serial = 0,
  previewSerial = 0;
const parentDirectory = computed(() =>
  directory.value.split('/').slice(0, -1).join('/'),
);
const downloadUrl = (file) =>
  '/api/taskinfo/artifact-download?' +
  new URLSearchParams({ run_id: props.runId, file });
const sizeText = (value) =>
  value < 1024
    ? `${value} B`
    : value < 1024 ** 2
      ? `${(value / 1024).toFixed(1)} KiB`
      : `${(value / 1024 ** 2).toFixed(1)} MiB`;
function closePreview() {
  previewSerial++;
  preview.value = null;
  previewLoading.value = false;
}
async function load(dir = '', start = 0) {
  const seq = ++serial;
  closePreview();
  loading.value = true;
  error.value = '';
  try {
    const data = await api.artifacts(props.runId, dir, start);
    if (seq !== serial) return;
    entries.value = data.entries;
    directory.value = dir;
    offset.value = start;
    hasMore.value = data.has_more;
    truncated.value = data.truncated;
    final.value = data.final;
  } catch (err) {
    if (seq === serial) error.value = err.message;
  } finally {
    if (seq === serial) loading.value = false;
  }
}
async function inspect(file) {
  const seq = ++previewSerial;
  previewLoading.value = true;
  error.value = '';
  try {
    const data = await api.artifactPreview(props.runId, file);
    if (seq === previewSerial) preview.value = data;
  } catch (err) {
    if (seq === previewSerial) error.value = err.message;
  } finally {
    if (seq === previewSerial) previewLoading.value = false;
  }
}
watch(
  () => props.runId,
  () => {
    serial++;
    entries.value = [];
    directory.value = '';
    offset.value = 0;
    hasMore.value = false;
    truncated.value = false;
    final.value = false;
    load();
  },
  { immediate: true },
);
watch(
  () => props.status,
  (value, previous) => {
    if (value && previous && value !== previous)
      load(directory.value, offset.value);
  },
);
onBeforeUnmount(() => {
  serial++;
  previewSerial++;
});
</script>
<style scoped>
.task-artifacts {
  display: grid;
  gap: 12px;
  min-width: 0;
}
.task-artifacts > .hint {
  margin: 0;
}
.artifact-table td:first-child {
  overflow-wrap: anywhere;
}
.artifact-table table {
  min-width: 460px;
}
.artifact-preview {
  display: grid;
  gap: 12px;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px;
  background: var(--panel-soft);
}
.artifact-preview pre {
  max-height: 400px;
  overflow: auto;
  margin: 0;
}
.artifact-csv {
  max-height: 400px;
  overflow: auto;
}
.artifact-csv td {
  white-space: pre-wrap;
  min-width: 100px;
  max-width: 400px;
  overflow-wrap: anywhere;
}
.artifact-csv tr:first-child {
  font-weight: 700;
  color: var(--brand-strong);
}
.artifact-preview .mono {
  overflow-wrap: anywhere;
}
.task-artifacts .filter-actions {
  align-items: center;
}
</style>
