<template>
  <details class="task-guide surface-card" @toggle="opened">
    <summary>
      任务编写示例 <span class="hint">从第一个任务到数据库访问</span>
    </summary>
    <div class="guide-content">
      <p class="hint">
        选一个示例，复制或下载为 main.py。任务每次执行使用独立 Python
        环境，入口运行结束即完成一次执行。
      </p>
      <p v-if="loading" role="status">正在读取示例…</p>
      <div v-if="error" class="inline-alert danger" role="alert">
        {{ error }}
        <button v-if="!editing" class="btn" @click="load">重新读取</button>
      </div>
      <div v-if="message" class="inline-alert success" role="status">
        {{ message }}
      </div>
      <div class="filter-actions">
        <button
          class="btn"
          :disabled="loading || editing || !example"
          @click="edit"
        >
          编辑此示例</button
        ><button
          class="btn"
          :disabled="loading || editing || !examples.length"
          @click="create"
        >
          新增示例类型</button
        ><span class="hint"
          >管理员保存后立即生效，服务重启后保留；不会执行示例代码。</span
        >
      </div>
      <form
        v-if="editing"
        class="guide-editor"
        aria-label="编辑任务示例"
        @submit.prevent="save"
      >
        <fieldset :disabled="saving">
          <div class="filter-grid">
            <div class="form-row">
              <label for="example-title">示例类型名称</label
              ><input
                id="example-title"
                v-model.trim="draft.title"
                class="input"
                required
                maxlength="60"
              />
            </div>
            <div class="form-row">
              <label for="example-filename">下载文件名</label
              ><input
                id="example-filename"
                v-model.trim="draft.filename"
                class="input"
                required
                maxlength="100"
              />
            </div>
            <div class="form-row">
              <label for="example-language">代码语言</label
              ><select
                id="example-language"
                v-model="draft.language"
                class="select"
              >
                <option value="python">Python</option>
                <option value="sql">SQL</option>
                <option value="bash">Shell</option>
                <option value="json">JSON</option>
                <option value="plaintext">纯文本 / requirements</option>
              </select>
            </div>
            <label class="checkbox-row"
              ><input
                v-model="draft.database"
                type="checkbox"
              />显示数据库使用说明</label
            >
          </div>
          <div class="form-row">
            <label for="example-description">示例说明</label
            ><input
              id="example-description"
              v-model="draft.description"
              class="input"
              maxlength="1000"
            />
          </div>
          <div class="form-row">
            <label for="example-note">补充提示</label
            ><input
              id="example-note"
              v-model="draft.note"
              class="input"
              maxlength="2000"
            />
          </div>
          <div class="form-row">
            <label for="example-code">示例源码</label
            ><textarea
              id="example-code"
              v-model="draft.code"
              class="input guide-source"
              rows="15"
              maxlength="65536"
              required
              spellcheck="false"
            ></textarea>
          </div>
          <details class="disclosure">
            <summary>预览代码高亮</summary>
            <CodeBlock
              class="guide-code"
              :code="draft.code"
              :language="draft.language"
              label="编辑预览代码"
            />
          </details>
          <div class="filter-actions">
            <button class="btn primary" :disabled="saving">
              {{ saving ? '保存中…' : '保存示例' }}</button
            ><button
              class="btn"
              type="button"
              :disabled="saving"
              @click="
                editing = false;
                error = '';
              "
            >
              取消编辑
            </button>
          </div>
        </fieldset>
      </form>
      <div v-if="example && !editing" class="guide-layout">
        <div class="guide-topics" role="group" aria-label="任务示例类型">
          <button
            v-for="item in examples"
            :key="item.id"
            class="btn"
            :class="selected === item.id ? 'primary' : ''"
            :aria-pressed="selected === item.id"
            @click="select(item.id)"
          >
            {{ item.title }}
          </button>
        </div>
        <section class="guide-example" aria-label="任务示例内容">
          <div class="guide-toolbar">
            <h3>{{ example.title }}</h3>
            <div class="filter-actions">
              <button class="btn" @click="copy">复制代码</button
              ><button class="btn" @click="download">
                下载 {{ example.filename }}
              </button>
            </div>
          </div>
          <p>{{ example.description }}</p>
          <p v-if="example.database" class="inline-alert info">
            先请管理员在“数据库连接 → 任务业务数据库”保存
            mysql_orders，或将示例中的标识换成已有业务连接。查询示例需要
            orders(id, status) 表；事务示例使用独立演示表 task_demo_items(id,
            status)。任务不能使用保留标识 platform。
          </p>
          <CodeBlock
            class="guide-code"
            :code="example.code"
            :language="example.language"
          />
          <p v-if="copyMessage" class="hint" role="status">{{ copyMessage }}</p>
          <p class="hint">{{ example.note }}</p>
        </section>
      </div>
      <div class="guide-notes">
        <section>
          <h3>打包与发布</h3>
          <ol>
            <li>
              ZIP 根目录放 main.py；其他模块、SQL、资源文件按相对目录一起打包。
            </li>
            <li>
              使用第三方库时，将 requirements.txt 放在 ZIP 根目录。Nexus
              模式自动解析间接依赖；离线模式需完整锁定并提供
              wheels/。任务不继承平台已安装的库。
            </li>
            <li>
              新增任务 → 上传 ZIP → 选择 main.py → 检查依赖环境 →
              查看差异并发布。
            </li>
            <li>
              在任务列表先手动执行，确认输出后再配置调度。首次发布默认不启用自动调度。
            </li>
          </ol>
        </section>
        <section>
          <h3>连接、日志与重复执行</h3>
          <ul>
            <li>
              用 with NewDB(...)
              自动归还连接。同一进程复用连接池，不同执行子进程各有自己的连接池。
            </li>
            <li>
              SQL 参数单独传递；大量操作分批处理。SQL 语法仍需符合目标数据库。
            </li>
            <li>
              print(..., flush=True)
              的输出可在执行记录查看；错误应抛出，让平台标记失败。
            </li>
            <li>
              重复执行应可安全重试。不要在脚本内启动无限循环或另一个定时器；输出写入
              WFS_TASK_DATA_DIR，并安排文件保留与清理。
            </li>
          </ul>
        </section>
      </div>
    </div>
  </details>
</template>
<script setup>
import { computed, reactive, ref } from 'vue';
import { api } from '../api';
import CodeBlock from './CodeBlock.vue';
const examples = ref([]),
  loading = ref(false),
  error = ref(''),
  message = ref(''),
  editing = ref(false),
  saving = ref(false);
const draft = reactive({});
const selected = ref('hello'),
  copyMessage = ref('');
const example = computed(() =>
  examples.value.find((item) => item.id === selected.value),
);
function opened(event) {
  if (event.target.open && !examples.value.length && !loading.value) load();
}
async function load() {
  loading.value = true;
  error.value = '';
  try {
    examples.value = (await api.taskExamples()).items;
    if (!example.value) selected.value = examples.value[0]?.id || '';
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}
function edit() {
  Object.assign(draft, { database: false }, example.value);
  editing.value = true;
  error.value = '';
  message.value = '';
}
function create() {
  Object.keys(draft).forEach((key) => delete draft[key]);
  Object.assign(draft, {
    title: '',
    filename: 'main.py',
    language: 'python',
    description: '',
    note: '',
    code: "def main():\n    print('Hello', flush=True)\n\n\nif __name__ == '__main__':\n    main()\n",
    database: false,
    revision: 0,
  });
  editing.value = true;
  error.value = '';
  message.value = '';
}
async function save() {
  if (saving.value) return;
  saving.value = true;
  error.value = '';
  try {
    const saved = await api.saveTaskExample({ ...draft });
    const index = examples.value.findIndex((item) => item.id === saved.id);
    if (index < 0) examples.value.push(saved);
    else examples.value[index] = saved;
    selected.value = saved.id;
    editing.value = false;
    message.value = '示例已保存。';
  } catch (err) {
    error.value = err.message;
  } finally {
    saving.value = false;
  }
}
function select(id) {
  selected.value = id;
  copyMessage.value = '';
}
async function copy() {
  const current = example.value;
  try {
    await navigator.clipboard.writeText(current.code);
    if (example.value === current) copyMessage.value = '代码已复制。';
  } catch {
    if (example.value === current)
      copyMessage.value = '浏览器未允许复制，请选中上方代码后复制。';
  }
}
function download() {
  const url = URL.createObjectURL(
    new Blob([example.value.code], { type: 'text/plain;charset=utf-8' }),
  );
  const link = document.createElement('a');
  link.href = url;
  link.download = example.value.filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
</script>
<style scoped>
.task-guide {
  min-width: 0;
}
.task-guide > summary {
  cursor: pointer;
  font-weight: 600;
  line-height: 1.7;
}
.task-guide > summary .hint {
  margin-left: 12px;
  font-weight: 400;
}
.guide-content {
  display: grid;
  gap: 20px;
  margin-top: 16px;
}
.guide-content p {
  margin: 0;
  line-height: 1.8;
}
.guide-editor {
  display: grid;
  gap: 16px;
  min-width: 0;
}
.guide-editor fieldset {
  display: grid;
  gap: 16px;
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.guide-editor .filter-grid .form-row {
  grid-template-rows: 20px 40px;
  align-content: start;
  gap: 8px;
}
.guide-editor .filter-grid .input,
.guide-editor .filter-grid .select {
  height: 40px;
  min-height: 40px;
  box-sizing: border-box;
}
.guide-source {
  font-family: var(--mono);
  min-height: 300px;
  line-height: 1.7;
  resize: vertical;
  white-space: pre;
}
.guide-editor .filter-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.guide-layout {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 20px;
}
.guide-topics {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-self: start;
}
.guide-topics .btn {
  text-align: left;
}
.guide-example {
  display: grid;
  min-width: 0;
  gap: 12px;
  align-content: start;
}
.guide-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}
.guide-content h3 {
  font-size: 15px;
  margin: 0;
}
.guide-code {
  max-height: 420px;
  overflow: auto;
  margin: 0;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-soft);
  line-height: 1.7;
  tab-size: 4;
}
.guide-notes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}
.guide-notes ol,
.guide-notes ul {
  margin: 10px 0 0;
  padding-left: 22px;
  line-height: 1.9;
}
@media (max-width: 760px) {
  .guide-editor .filter-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .guide-layout,
  .guide-notes {
    grid-template-columns: minmax(0, 1fr);
  }
  .guide-topics {
    flex-direction: row;
    flex-wrap: wrap;
  }
  .task-guide > summary .hint {
    display: block;
    margin-left: 0;
  }
}
</style>
