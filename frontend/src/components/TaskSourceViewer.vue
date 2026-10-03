<template>
  <section class="task-source-viewer" aria-label="任务文件只读查看">
    <p class="hint">当前部署的任务文件 · 只读</p>
    <div v-if="error" class="inline-alert danger" role="alert">{{ error }}</div>
    <LoadingStatus v-if="showLoadingStatus" :active="loading" label="正在读取任务文件…" />
    <div class="source-browser">
      <aside class="source-files" aria-label="任务目录文件列表">
        <div class="source-toolbar"><button class="btn" :disabled="loading || !directory" @click="loadDirectory(parentDirectory)">上级目录</button><button class="btn" :disabled="loading" @click="loadDirectory(directory)">刷新文件</button></div>
        <p class="source-directory mono">任务目录 / {{ directory }}</p>
        <button v-for="entry in entries" :key="entry.path" class="source-file-item" :class="{ selected: entry.path === selected }" :disabled="loading || entry.type === 'unavailable'" @click="entry.type === 'directory' ? loadDirectory(entry.path) : openFile(entry.path)">
          <span>{{ entry.type === 'directory' ? '目录' : entry.type === 'unavailable' ? '链接/特殊文件' : '文件' }}</span><strong>{{ entry.name }}</strong><small v-if="entry.is_entry">入口</small>
        </button>
        <button v-if="hasMore" class="btn" :disabled="loading" @click="loadDirectory(directory, true)">加载更多文件</button>
        <p v-if="truncated" class="hint">目录超过 20000 项扫描上限，其余文件请在服务器查看。</p>
        <p v-if="!loading && !entries.length" class="hint">此目录为空。</p>
      </aside>
      <div class="source-preview" :aria-busy="loading">
        <div class="source-toolbar"><button class="btn" :disabled="!source || loading" @click="openFile(source.path)">刷新当前文件</button><button class="btn" :disabled="source?.kind !== 'text' || loading" @click="copy">{{ copied ? '已复制' : '复制内容' }}</button><label v-if="source?.kind === 'text'" class="source-wrap"><input v-model="wrap" type="checkbox">自动换行</label></div>
        <p v-if="!source && !loading" class="hint">请选择任务目录中的文件。</p>
        <template v-if="source">
          <p class="source-meta mono">{{ source.path }} · {{ source.encoding || source.mime_type }} · {{ (source.size / 1024).toFixed(1) }} KiB · 修改于 {{ source.modified_at }}<template v-if="source.sha256"> · 校验 {{ source.sha256.slice(0,12) }}</template></p>
          <template v-if="source.kind === 'text'">
            <div class="source-toolbar"><label for="source-search">搜索文件内容<input id="source-search" v-model="search" class="input" placeholder="输入内容定位行" @input="matchIndex = 0; locate()"></label><span aria-live="polite">{{ search ? `${matches.length ? matchIndex + 1 : 0} / ${matches.length} 处` : `共 ${lines.length} 行` }}</span><button class="btn" :disabled="!matches.length" @click="jumpMatch(-1)">上一处</button><button class="btn" :disabled="!matches.length" @click="jumpMatch(1)">下一处</button></div>
            <div ref="codeView" class="source-code" :class="{ 'source-wrapped': wrap }" aria-label="只读文件内容">
              <div v-for="(line,index) in pageLines" :key="page * PAGE_SIZE + index" class="source-line" :class="{ 'source-match': matches.includes((page - 1) * PAGE_SIZE + index) }"><span class="source-line-number" aria-hidden="true">{{ (page - 1) * PAGE_SIZE + index + 1 }}</span><code>{{ line || ' ' }}</code></div>
            </div>
            <div class="source-pagination"><span>第 {{ page }} / {{ pageCount }} 页 · 每页 {{ PAGE_SIZE }} 行</span><button class="btn" :disabled="page === 1" @click="changePage(-1)">上一页内容</button><button class="btn" :disabled="page === pageCount" @click="changePage(1)">下一页内容</button></div>
          </template>
          <img v-else-if="source.kind === 'image'" class="source-image" :src="source.data_url" :alt="source.path">
          <p v-else class="inline-alert">{{ source.reason }}</p>
        </template>
      </div>
    </div>
  </section>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { api } from '../api';
import LoadingStatus from './LoadingStatus.vue';
const props = defineProps({ pid: { type: String, required: true }, showLoadingStatus: { type: Boolean, default: true } });
const emit = defineEmits(['loading']);
const entries = ref([]), directory = ref(''), selected = ref(''), source = ref(null), loading = ref(false), error = ref('');
const hasMore = ref(false), truncated = ref(false), nextOffset = ref(0);
const search = ref(''), matchIndex = ref(0), page = ref(1), copied = ref(false), wrap = ref(false);
const codeView = ref(null);
watch(loading, value => emit('loading', value));
const PAGE_SIZE = 200;
let generation = 0;
const parentDirectory = computed(() => directory.value.split('/').slice(0,-1).join('/'));
const lines = computed(() => source.value?.content?.split('\n') || []);
const pageCount = computed(() => Math.max(1, Math.ceil(lines.value.length / PAGE_SIZE)));
const pageLines = computed(() => lines.value.slice((page.value-1)*PAGE_SIZE, page.value*PAGE_SIZE));
const matches = computed(() => search.value ? lines.value.flatMap((line,index) => line.toLowerCase().includes(search.value.toLowerCase()) ? [index] : []) : []);
async function locate() {
  if (!matches.value.length) return;
  const line = matches.value[matchIndex.value];
  page.value = Math.floor(line / PAGE_SIZE)+1;
  await nextTick();
  codeView.value?.children[line % PAGE_SIZE]?.scrollIntoView({ block: 'nearest' });
}
function changePage(step) { page.value += step; if (codeView.value) codeView.value.scrollTop = 0; }
function jumpMatch(step) { matchIndex.value = (matchIndex.value + step + matches.value.length) % matches.value.length; locate(); }
async function openFile(filename) {
  if (!filename) return;
  const seq = ++generation;
  loading.value = true; error.value = '';
  try {
    const result = await api.taskSource(props.pid, filename);
    if (seq === generation) {
      const sameFile = source.value?.path === filename;
      source.value = result; selected.value = filename; copied.value = false;
      if (!sameFile) { search.value = ''; page.value = 1; matchIndex.value = 0; }
      page.value = Math.min(page.value, pageCount.value);
      matchIndex.value = Math.min(matchIndex.value, Math.max(0, matches.value.length - 1));
    }
  }
  catch (err) { if (seq === generation) error.value = err.message; }
  finally { if (seq === generation) loading.value = false; }
}
async function loadDirectory(path = '', more = false) {
  const seq = ++generation;
  loading.value = true; error.value = '';
  try {
    const result = await api.taskSources(props.pid, path, more ? nextOffset.value : 0);
    if (seq !== generation) return;
    directory.value = path; entries.value = more ? [...entries.value,...result.entries] : result.entries;
    hasMore.value = result.has_more; truncated.value = result.truncated; nextOffset.value = result.next_offset;
    loading.value = false;
    if (!more && !source.value) {
      const initial = path === '' && result.main_file ? result.main_file : result.entries.find(entry => entry.type === 'file')?.path;
      if (initial) await openFile(initial);
    }
  } catch (err) { if (seq === generation) error.value = err.message; }
  finally { if (seq === generation) loading.value = false; }
}
async function copy() {
  try { await navigator.clipboard.writeText(source.value.content); copied.value = true; }
  catch { error.value = '浏览器未允许复制，请在文件区域选择内容复制。'; }
}
watch(() => props.pid, () => { generation++; entries.value = []; directory.value = ''; selected.value = ''; source.value = null; loadDirectory(); }, { immediate: true });
onBeforeUnmount(() => generation++);
</script>
