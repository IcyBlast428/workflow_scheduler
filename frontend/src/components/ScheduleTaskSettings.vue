<template>
<div class="schedule-overview">
  <div class="runtime-card">
    <label class="toggle-row">
      <input v-model="form.enabled" type="checkbox" />
      <span>
        <strong>启用自动调度</strong>
        <small
          >关闭后任务保持停止状态，但仍可在列表中手动触发。</small
        >
      </span>
    </label>
    <div class="schedule-grid">
      <div class="form-row">
        <label for="task-name">任务名称</label>
        <input
          id="task-name"
          v-model.trim="form.task_name"
          class="input"
          placeholder="展示名称"
        />
      </div>
      <div class="form-row">
        <span class="field-label">当前执行入口</span><code class="entry-summary">{{ form.main_file || '沿用发布入口' }}</code>
        <details class="entry-override"><summary>高级：覆盖执行入口</summary><p class="hint">通常在代码发布时设置。仅在已发布文件中切换入口；此项不会安装依赖或发布新代码。</p><label for="main-file">入口文件</label>
        <input
          id="main-file"
          v-model.trim="form.main_file"
          class="input"
          list="main-file-options"
          placeholder="main.py"
        />
        <datalist id="main-file-options">
          <option
            v-for="item in mainFileOptions"
            :key="item"
            :value="item"
          ></option>
        </datalist></details>
      </div>
      <div class="form-row">
        <label for="max-instances">同时执行上限</label>
        <input
          id="max-instances"
          v-model.number="form.max_instances"
          class="input"
          type="number"
          min="1"
        />
      </div>
      <div class="form-row">
        <label for="timeout-seconds">超时秒数</label>
        <input
          id="timeout-seconds"
          v-model.number="form.timeout_seconds"
          class="input"
          type="number"
          min="0"
        />
      </div>
    </div>
  </div>

  <section class="runtime-card schedule-metadata">
    <strong>负责人、说明与执行资源</strong>
    <div class="schedule-grid">
      <div class="form-row">
        <label for="schedule-owner">负责人</label
        ><input
          id="schedule-owner"
          v-model.trim="form.owner"
          class="input"
          maxlength="200"
        />
      </div>
      <div class="form-row">
        <label for="task-description">任务说明</label
        ><textarea
          id="task-description"
          v-model="form.description"
          class="input"
          maxlength="10000"
          rows="1"
        ></textarea>
      </div>
      <div class="form-row">
        <label for="task-memory">内存地址空间上限（MiB）</label
        ><input
          id="task-memory"
          v-model.number="form.memory_mb"
          class="input"
          type="number"
          min="0"
        />
      </div>
      <div class="form-row">
        <label for="task-cpu">CPU 时间上限（秒）</label
        ><input
          id="task-cpu"
          v-model.number="form.cpu_seconds"
          class="input"
          type="number"
          min="0"
        />
      </div>
      <div class="form-row">
        <label for="task-file">单文件大小上限（MiB）</label
        ><input
          id="task-file"
          v-model.number="form.file_mb"
          class="input"
          type="number"
          min="0"
        />
      </div>
      <div class="form-row">
        <label for="task-misfire">调度延迟容忍（秒）</label
        ><input
          id="task-misfire"
          v-model.number="form.misfire_grace_seconds"
          class="input"
          type="number"
          min="1"
        />
      </div>
    </div>
    <p class="hint">
      资源上限填 0 表示不限，由 Linux
      执行。服务中断后的任务可确认业务数据后手动补跑。
    </p>
  </section>
</div>
</template>
<script setup>
// All sections edit the same draft; saving, dirty checks and resets belong to ScheduleDialog.
defineProps({form:{type:Object,required:true},mainFileOptions:{type:Array,default:()=>[]}});
</script>
<style scoped>
.entry-summary{display:block;padding:10px 12px;min-height:40px;background:var(--panel-soft);border-radius:6px;overflow-wrap:anywhere}.entry-override{margin-top:8px}.entry-override summary{cursor:pointer;color:var(--muted);font-size:13px}.entry-override .hint{line-height:1.6}.field-label{min-height:20px;line-height:20px;font-weight:600}
</style>
