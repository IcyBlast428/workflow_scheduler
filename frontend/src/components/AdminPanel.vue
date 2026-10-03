<template>
  <section class="panel admin-panel">
    <div class="panel-head"><div><h2>账户与操作记录</h2><p>查看者可读；操作员可触发、启停任务；管理员可维护配置与账户。</p></div><button class="btn" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新' }}</button></div>
    <LoadingStatus :active="loading" label="正在更新维护状态与账户…" />
    <div class="panel-body">
    <div v-if="error" class="inline-alert danger" role="alert">{{ error }}</div><div v-if="message" class="inline-alert success" role="status">{{ message }}</div>
    <section class="surface-card runtime-status" aria-labelledby="runtime-heading">
      <div class="section-heading"><h3 id="runtime-heading">运行维护状态</h3><p>查看记录补写、历史汇总与通知发送情况。</p></div>
      <div class="admin-metrics">
        <div class="mini-stat"><span>剩余空间</span><strong>{{ runtime.free_mb ?? '-' }} <small>MiB</small></strong></div>
        <div class="mini-stat"><span>等待补写</span><strong>{{ runtime.journal?.pending_writes ?? '-' }} <small>条</small></strong></div>
        <div class="mini-stat"><span>历史统计</span><strong class="stat-status">{{ runtime.summary?.complete ? '已补算完成' : '补算中' }}</strong></div>
        <div class="mini-stat"><span>本地记录占用</span><strong>{{ ((runtime.journal?.journal_bytes || 0)/1024/1024).toFixed(1) }} <small>MiB</small></strong></div>
      </div>
      <p class="runtime-meta">上次维护：{{ (runtime.maintenance?.maintenance?.completed_at || '-').split('.')[0] }}</p>
      <p v-if="runtime.journal?.oldest_pending" class="runtime-meta">最早待补写：{{ runtime.journal.oldest_pending }}</p>
      <div class="runtime-alerts"><span class="tag info">待发告警 {{ runtime.alerts?.pending || 0 }}</span><span class="tag warning">待核对 {{ runtime.alerts?.unknown || 0 }}</span><span class="tag danger">发送失败 {{ runtime.alerts?.failed || 0 }}</span></div>
      <details class="disclosure"><summary>接口与数据库耗时 <span class="muted">最近最多 512 次采样</span></summary>
        <div class="table-wrap"><table class="runtime-metrics"><thead><tr><th>接口 / 数据库操作</th><th>P95</th><th>最大耗时</th></tr></thead><tbody><tr v-for="(metric,name) in runtime.metrics || {}" :key="name"><td class="mono">{{ name }}</td><td>{{ metric.p95_ms }} ms</td><td>{{ metric.max_ms }} ms</td></tr></tbody></table><p v-if="!Object.keys(runtime.metrics || {}).length" class="table-empty-note">暂无采样记录。</p></div>
      </details>
    </section>
    <section class="admin-section" aria-labelledby="accounts-heading">
    <div class="section-heading"><h3 id="accounts-heading">账户管理</h3><p>填写账户信息，或从列表中选择已有账户。</p></div>
    <form class="filter-grid account-form" @submit.prevent="save">
      <div class="form-row"><label for="account-name">用户名</label><input id="account-name" v-model.trim="form.username" class="input" required maxlength="100"></div>
      <div class="form-row"><label for="account-password">设置密码</label><input id="account-password" v-model="form.password" class="input" type="password" autocomplete="new-password" minlength="12" placeholder="已有账户留空表示不变"></div>
      <div class="form-row"><label for="account-role">角色</label><select id="account-role" v-model="form.role" class="select"><option value="viewer">查看者</option><option value="operator">操作员</option><option value="admin">管理员</option></select></div>
      <div class="filter-actions"><label class="checkbox-row"><input v-model="form.enabled" type="checkbox">允许登录</label><button class="btn primary" :disabled="saving">保存账户</button></div>
    </form>
    <div class="table-wrap"><table><thead><tr><th>用户名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in accounts" :key="item.username"><td>{{ item.username }}</td><td>{{ roles[item.role] }}</td><td>{{ item.enabled ? '启用' : '禁用' }}</td><td><span v-if="item.managed_by">通过服务配置管理</span><button v-else class="btn" @click="edit(item)">编辑</button></td></tr></tbody></table></div>
    </section>
    <section class="admin-section" aria-labelledby="audit-heading"><div class="section-heading"><h3 id="audit-heading">最近 100 条操作记录</h3></div><div class="table-wrap"><table><thead><tr><th>操作人</th><th>操作</th><th>对象</th><th>结果</th><th>时间</th></tr></thead><tbody><tr v-for="(item,index) in records" :key="index"><td>{{ item.actor }}</td><td>{{ actionLabel(item.action) }}</td><td>{{ item.target || '-' }}</td><td><span class="tag" :class="item.outcome === 'success' ? 'success' : 'danger'">{{ item.outcome === 'success' ? '成功' : '失败' }}</span></td><td class="nowrap">{{ item.created_at }}</td></tr></tbody></table><p v-if="!records.length" class="table-empty-note">暂无操作记录。</p></div></section>
    </div>
  </section>
</template>
<script setup>
import { ref, reactive, onMounted } from 'vue';
import { api } from '../api';
import { actionLabel } from '../executionLabels';
import LoadingStatus from './LoadingStatus.vue';
const accounts = ref([]), records = ref([]), error = ref(''), message = ref(''), saving = ref(false);
const runtime = ref({});
const loading = ref(false);
const roles = {viewer:'查看者',operator:'操作员',admin:'管理员'};
const form = reactive({username:'',password:'',role:'viewer',enabled:true});
function edit(item) { Object.assign(form,{...item,password:'',enabled:Boolean(item.enabled)}); message.value = ''; }
async function load() { if (loading.value) return; loading.value = true; try { [accounts.value, records.value,runtime.value] = await Promise.all([api.users(),api.audit(),api.runtime()]); error.value = ''; } catch (err) { error.value = err.message; } finally { loading.value = false; } }
async function save() { saving.value = true; try { message.value = await api.saveUser({...form}); form.password = ''; await load(); } catch (err) { error.value = err.message; } finally { saving.value = false; } }
onMounted(load);
</script>
