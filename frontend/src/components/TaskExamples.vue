<template>
  <section class="panel task-examples">
    <div class="panel-head"><div><h2>任务示例</h2><p>从示例开始编写任务，提交到 GitLab 后，在任务列表审查并发布。</p></div></div>
    <div class="panel-body examples-body">
      <TaskWritingGuide open />
      <section class="surface-card"><h3>完整项目示例</h3><p class="hint">包含源码、资源和输出目录用法，可下载后加入 GitLab 任务目录。</p><div class="filter-actions"><a class="btn" href="/api/taskinfo/packages/example?kind=outputs" download>下载文件输出示例 ZIP</a><a class="btn" href="/api/taskinfo/packages/example?kind=nested" download>下载多层目录示例 ZIP</a></div></section>
      <section class="surface-card"><h3>从 GitLab 发布</h3><ol><li>在 app/jobs/分类/任务 中编写代码，依赖放在任务根目录 requirements.txt。</li><li>为任务创建 .wfs-task.json，填写稳定 task_id；多个入口时指定 main_file。</li><li>合并到目标分支后，在任务列表检查文件差异和依赖，再确认发布。</li></ol><p class="hint">运行输出请写入 WFS_TASK_DATA_DIR。更新、回滚或删除任务都保留这个目录。</p></section>
    </div>
  </section>
</template>
<script setup>
import TaskWritingGuide from './TaskWritingGuide.vue';
</script>
<style scoped>
.examples-body{display:grid;gap:24px}.surface-card{min-width:0}.surface-card p{margin:12px 0 18px}.surface-card ol{padding-left:22px;line-height:2;overflow-wrap:anywhere}
</style>
