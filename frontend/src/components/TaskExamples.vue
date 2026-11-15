<template>
  <section class="panel task-examples">
    <div class="panel-head"><div><h2>任务示例</h2><p>从示例开始编写任务，提交到 GitLab 后，在任务列表审查并发布。</p></div></div>
    <div class="panel-body examples-body">
      <TaskWritingGuide open />
      <DatabaseUsageExamples kind="business" :connection-id="exampleConnection" :dialect="exampleDialect">
        <template #settings>
          <div class="database-example-settings">
            <label>示例连接标识<input class="input" v-model.trim="exampleConnection" maxlength="100" placeholder="例如 reports" autocomplete="off" /><small class="hint">替换为任务已获授权的连接标识；此处仅调整示例代码。</small></label>
            <label>示例数据库类型<select class="select" v-model="exampleDialect"><option value="mysql">MySQL / PolarDB / MariaDB</option><option value="postgresql">PostgreSQL</option><option value="gaussdb">GaussDB / DWS</option><option value="clickhouse">ClickHouse</option></select></label>
          </div>
        </template>
      </DatabaseUsageExamples>
      <section class="surface-card"><h3>完整项目示例</h3><p class="hint">包含源码、资源和输出目录用法，可下载后加入 GitLab 任务目录。</p><div class="filter-actions"><a class="btn" href="/api/taskinfo/packages/example?kind=outputs" download>下载文件输出示例 ZIP</a><a class="btn" href="/api/taskinfo/packages/example?kind=nested" download>下载多层目录示例 ZIP</a><a v-for="item in [{id:'report_flow',name:'参数报表'},{id:'database_transaction',name:'多表事务与 DDL'},{id:'retry_once',name:'自动重试'},{id:'business_backfill',name:'业务日期补跑'},{id:'queue_observer',name:'排队与资源'},{id:'business_connection',name:'业务连接模板（需配置）'}]" :key="item.id" class="btn" :href="'/api/taskinfo/packages/example?kind='+item.id" download>下载{{ item.name }}示例</a></div></section>
      <section class="surface-card"><h3>从 GitLab 发布</h3><ol><li>在 app/jobs/分类/任务 中编写代码，依赖放在任务根目录 requirements.txt。</li><li>无需创建任务描述文件；平台自动生成唯一 task_id，在发布页面填写任务名称并选择 Python 入口。</li><li>合并到目标分支后，在任务列表检查文件差异和依赖，再确认发布。</li></ol><p class="hint">运行输出请写入 WFS_TASK_DATA_DIR。更新、回滚或删除任务都保留这个目录。</p></section>
    </div>
  </section>
</template>
<script setup>
import {ref} from 'vue';
import TaskWritingGuide from './TaskWritingGuide.vue';
import DatabaseUsageExamples from './DatabaseUsageExamples.vue';
// 文档只生成示例，不读取管理页的实际连接目录或凭据。
const exampleConnection=ref('reports'),exampleDialect=ref('postgresql');
</script>
<style scoped>
.examples-body{display:grid;gap:24px}.surface-card{min-width:0}.surface-card p{margin:12px 0 18px}.surface-card ol{padding-left:22px;line-height:2;overflow-wrap:anywhere}
.database-example-settings{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr));gap:16px;min-width:0}.database-example-settings label{display:grid;gap:8px;align-content:start;min-width:0}.database-example-settings .hint{line-height:1.6;overflow-wrap:anywhere}
</style>
