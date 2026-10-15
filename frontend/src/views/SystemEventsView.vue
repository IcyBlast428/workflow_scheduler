<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>平台事件</h2>
        <p>查看调度器事件、任务异常和系统级报错记录。</p>
      </div>
    </div>
    <form class="filter-grid logs" @submit.prevent="$emit('search')">
      <div class="form-row">
        <label for="system-log-id">任务 ID</label>
        <input
          id="system-log-id"
          v-model.trim="systemLogs.params.systemids"
          class="input"
          list="system-id-options"
          placeholder="PID"
        />
        <datalist id="system-id-options">
          <option
            v-for="item in systemLogs.ids"
            :key="item.id"
            :value="item.id"
          ></option>
        </datalist>
      </div>
      <div class="form-row">
        <label for="system-log-start">开始日期</label>
        <input
          id="system-log-start"
          v-model="systemLogs.params.startDate"
          class="input"
          type="date"
        />
      </div>
      <div class="form-row">
        <label for="system-log-end">结束日期</label>
        <input
          id="system-log-end"
          v-model="systemLogs.params.endDate"
          class="input"
          type="date"
        />
      </div>
      <div class="filter-actions">
        <button class="btn primary" type="submit">
          <span class="btn-icon">?</span>
          搜索
        </button>
        <button class="btn" type="button" @click="$emit('reset')">清空</button>
      </div>
    </form>
    <LoadingStatus :active="systemLogs.loading" label="正在更新平台事件…" />
    <LogTable
      kind="system"
      :rows="systemLogs.rows"
      :loading="systemLogs.loading"
      :error="systemLogs.error"
      @open="$emit('open', $event)"
    />
    <Pagination
      :page="systemLogs.params.currentPage"
      :page-size="systemLogs.params.pagesize"
      :total="systemLogs.total"
      :exact="false"
      :has-more="systemLogs.hasMore"
      @page="$emit('page', $event)"
      @page-size="$emit('page-size', $event)"
    />
  </section>
</template>
<script setup>
import LogTable from '../components/LogTable.vue';
import Pagination from '../components/Pagination.vue';
import LoadingStatus from '../components/LoadingStatus.vue';
defineProps({ systemLogs: { type: Object, required: true } });
defineEmits(['search', 'reset', 'open', 'page', 'page-size']);
</script>
