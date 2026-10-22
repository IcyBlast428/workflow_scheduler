<template>
  <details class="task-guide surface-card">
    <summary>
      任务编写示例 <span class="hint">从第一个任务到数据库访问</span>
    </summary>
    <div class="guide-content">
      <p class="hint">
        选一个示例，复制或下载为 main.py。任务每次执行使用独立 Python
        环境，入口运行结束即完成一次执行。
      </p>
      <div class="guide-layout">
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
          <pre
            class="guide-code"
            tabindex="0"
            aria-label="示例代码"
          ><code>{{ example.code }}</code></pre>
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
              使用第三方库时，加入完整锁定的 requirements.txt 和
              wheels/。独立任务环境不继承平台已安装的库。
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
import { computed, ref } from 'vue';
import hello from '../../../examples/tasks/hello/main.py?raw';
import query from '../../../examples/tasks/database_query/main.py?raw';
import transaction from '../../../examples/tasks/database_transaction/main.py?raw';
import output from '../../../examples/tasks/file_output/main.py?raw';
import dependencies from '../../../examples/tasks/prepare-dependencies.txt?raw';

const examples = [
  {
    id: 'hello',
    title: '第一个任务',
    filename: 'main.py',
    code: hello,
    description:
      '只用 Python 标准库，无需 requirements.txt。将此文件直接放在 ZIP 根目录即可开始。',
    note: '成功执行会输出合计 5050。任务按普通 Python 脚本运行，不需要定义平台装饰器。',
  },
  {
    id: 'query',
    title: '数据库查询',
    filename: 'main.py',
    code: query,
    database: true,
    description:
      '使用管理员保存的连接标识查询数据库，不在代码中填写地址或密码。',
    note: '先查看“离线依赖准备”，安装 NewDB 所需库和对应驱动。先用演示表测试，再改为实际业务表与过滤条件。',
  },
  {
    id: 'transaction',
    title: '事务与批量写入',
    filename: 'main.py',
    code: transaction,
    database: true,
    description:
      '在一个事务里处理一批更新，失败时整批回滚。只在演示业务库中准备测试数据。',
    note: '数据库账号需有对应表的 UPDATE 权限。ClickHouse 不支持此事务示例；事务内不要做耗时网络请求。',
  },
  {
    id: 'output',
    title: '生成报表文件',
    filename: 'main.py',
    code: output,
    description:
      '将 CSV 保存到平台提供的任务数据目录，使用独立文件名处理并发执行。',
    note: '无需第三方依赖。任务数据目录用于持久化输出；不要向已发布的代码目录写文件。',
  },
  {
    id: 'dependencies',
    title: '离线依赖准备',
    filename: 'prepare-dependencies.txt',
    code: dependencies,
    description:
      '以下是准备依赖的命令说明，供联网的构建环境使用，不是任务入口。',
    note: 'Web 页“驱动就绪”只表示平台测试连接的环境具备驱动；任务自己的环境也必须安装。GaussDB 的驱动需按实际型号验收。',
  },
];
const selected = ref('hello'),
  copyMessage = ref('');
const example = computed(() =>
  examples.find((item) => item.id === selected.value),
);
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
