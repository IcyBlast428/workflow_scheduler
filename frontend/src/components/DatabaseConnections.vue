<template>
  <section class="panel connection-panel">
    <div class="panel-head">
      <div>
        <h2>数据库连接</h2>
        <p>配置 PolarDB for MySQL / MySQL 8.0 及以上版本。</p>
      </div>
      <button class="btn" :disabled="busy || loading" @click="load">
        刷新
      </button>
    </div>
    <div class="panel-body">
      <LoadingStatus
        v-if="loading"
        :active="loading"
        label="正在读取连接设置…"
      />
      <div v-if="error" class="inline-alert danger" role="alert">
        {{ error }}
      </div>
      <div v-if="message" class="inline-alert success" role="status">
        {{ message }}
      </div>
      <div class="surface-card connection-current">
        <strong>当前平台库：{{ state.active_dialect || '读取中' }}</strong
        ><span v-if="state.active"
          >{{ state.active.host }}:{{ state.active.port }} /
          {{ state.active.database }}</span
        >
        <p v-if="state.restart_required" class="inline-alert warning">
          平台连接已保存，等待统一重启所有 Web 和调度进程后生效。
        </p>
        <p v-else class="hint">
          平台库保存任务配置、执行记录和账户。切换连接不会搬迁原库数据。
        </p>
      </div>
      <div class="filter-actions connection-tabs" aria-label="连接类型">
        <button
          class="btn"
          :class="scope === 'platform' ? 'primary' : ''"
          :aria-pressed="scope === 'platform'"
          :disabled="Boolean(busy)"
          @click="selectScope('platform')"
        >
          平台数据库
        </button>
        <button
          class="btn"
          :class="scope === 'business' ? 'primary' : ''"
          :aria-pressed="scope === 'business'"
          :disabled="Boolean(busy)"
          @click="selectScope('business')"
        >
          任务业务数据库
        </button>
      </div>
      <div
        v-if="scope === 'business'"
        class="filter-actions connection-profiles"
      >
        <button
          v-for="profile in businessProfiles"
          :key="profile.id"
          class="btn"
          :disabled="Boolean(busy)"
          @click="edit(profile)"
        >
          {{ profile.id }}</button
        ><button class="btn" :disabled="Boolean(busy)" @click="newBusiness">
          ＋ 新建业务连接
        </button>
      </div>
      <p class="hint">
        {{
          scope === 'platform'
            ? '先测试连接；新建空库可初始化平台表。测试通过且结构完整后才能保存，保存后需统一重启服务。'
            : '使用固定的连接标识关联任务。保存后，任务下次建立连接时读取新配置。'
        }}
      </p>
      <form class="connection-form" @submit.prevent="run('save')">
        <fieldset :disabled="busy || loading">
          <div class="filter-grid">
            <div class="form-row">
              <label for="db-id">连接标识</label
              ><input
                id="db-id"
                v-model.trim="form.id"
                class="input"
                :readonly="scope === 'platform' || editing"
                required
                pattern="[A-Za-z][A-Za-z0-9_-]{0,99}"
                maxlength="100"
                placeholder="例如 mysql_orders"
              /><small class="hint">{{
                scope === 'platform'
                  ? '平台连接固定为 platform'
                  : '任务通过 NewDB(连接标识) 使用，既有标识无需改动脚本。'
              }}</small>
            </div>
            <div class="form-row">
              <label for="db-host">数据库地址</label
              ><input
                id="db-host"
                v-model.trim="form.host"
                class="input"
                required
                maxlength="253"
                placeholder="PolarDB 集群地址或主地址"
              />
            </div>
            <div class="form-row">
              <label for="db-port">端口</label
              ><input
                id="db-port"
                v-model.number="form.port"
                class="input"
                type="number"
                required
                min="1"
                max="65535"
              />
            </div>
            <div class="form-row">
              <label for="db-name">数据库名称</label
              ><input
                id="db-name"
                v-model.trim="form.database"
                class="input"
                required
                maxlength="64"
                placeholder="例如 workflow_scheduler"
              />
            </div>
            <div class="form-row">
              <label for="db-user">数据库用户名</label
              ><input
                id="db-user"
                v-model.trim="form.user"
                class="input"
                required
                maxlength="100"
                autocomplete="off"
              />
            </div>
            <div class="form-row">
              <label for="db-password">数据库密码</label
              ><input
                id="db-password"
                v-model="form.password"
                class="input"
                type="password"
                autocomplete="new-password"
                :required="!form.password_set"
                maxlength="1024"
                :placeholder="
                  form.password_set
                    ? '已设置，留空保留原密码'
                    : '请输入数据库密码'
                "
              /><small class="hint">密码加密保存，接口不回传原文。</small>
            </div>
            <div class="form-row">
              <label for="db-tls">连接加密</label
              ><select id="db-tls" v-model="form.tls" class="select">
                <option value="verify_identity">TLS（校验证书和主机名）</option>
                <option value="disabled">不使用 TLS</option>
              </select>
            </div>
            <div v-if="form.tls === 'verify_identity'" class="form-row">
              <label for="db-ca">服务器 CA 证书路径</label
              ><input
                id="db-ca"
                v-model.trim="form.ssl_ca"
                class="input"
                required
                placeholder="例如 /etc/wfs/certs/polardb-ca.pem"
              /><small class="hint"
                >文件需在 Web、调度和任务运行环境的相同路径可读。</small
              >
            </div>
          </div>
          <div class="filter-actions">
            <button class="btn" type="button" @click="run('test')">
              {{ busy === 'test' ? '测试中…' : '测试连接' }}</button
            ><button class="btn primary" type="submit">
              {{
                busy === 'save'
                  ? '保存中…'
                  : scope === 'platform'
                    ? '测试并保存（重启生效）'
                    : '测试并保存'
              }}
            </button>
          </div>
          <details v-if="scope === 'platform'" class="disclosure">
            <summary>新数据库初始化</summary>
            <p class="hint">
              仅用于没有平台表的新库，需要建表权限。已有数据的库请先完成数据迁移和结构核对。
            </p>
            <div class="form-row">
              <label for="db-initialize-name">输入数据库名称确认初始化</label
              ><input
                id="db-initialize-name"
                v-model.trim="confirmDatabase"
                class="input"
                autocomplete="off"
              />
            </div>
            <button
              class="btn warning"
              type="button"
              :disabled="confirmDatabase !== form.database || !form.database"
              @click="initialize"
            >
              初始化新库平台表
            </button>
          </details>
        </fieldset>
      </form>
      <div
        v-if="result"
        class="inline-alert"
        :class="result.ready ? 'success' : 'warning'"
        role="status"
      >
        <strong>{{
          result.ready ? '连接与结构检查通过' : '已连通，平台结构尚不完整'
        }}</strong
        ><span>{{ result.version }} · {{ result.database }}</span
        ><span v-if="result.missing?.length"
          >缺少：{{ result.missing.join('、') }}</span
        >
      </div>
    </div>
  </section>
</template>
<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { api } from '../api';
import LoadingStatus from './LoadingStatus.vue';
const props = defineProps({ confirm: { type: Function, required: true } });
const state = ref({}),
  scope = ref('platform'),
  busy = ref(''),
  loading = ref(false),
  error = ref(''),
  message = ref(''),
  result = ref(null),
  editing = ref(false),
  confirmDatabase = ref('');
const empty = () => ({
  id: '',
  host: '',
  port: 3306,
  database: '',
  user: '',
  password: '',
  password_set: false,
  tls: 'verify_identity',
  ssl_ca: '',
  revision: 0,
});
const form = reactive(empty());
const businessProfiles = computed(() =>
  (state.value.profiles || []).filter((item) => item.id !== 'platform'),
);
function edit(profile) {
  Object.assign(form, empty(), profile, { password: '' });
  editing.value = Boolean(profile.revision);
  error.value = '';
  message.value = '';
  result.value = null;
  confirmDatabase.value = '';
}
function newBusiness() {
  edit(empty());
}
function selectScope(value) {
  scope.value = value;
  edit(
    value === 'platform'
      ? (state.value.profiles || []).find((item) => item.id === 'platform') || {
          ...empty(),
          id: 'platform',
        }
      : businessProfiles.value[0] || empty(),
  );
}
async function load(preserve = false) {
  loading.value = true;
  error.value = '';
  try {
    state.value = await api.databaseConnections();
    if (!preserve) selectScope(scope.value);
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}
watch(form, () => {
  result.value = null;
  message.value = '';
});
async function run(action) {
  if (busy.value) return;
  busy.value = action;
  error.value = '';
  message.value = '';
  result.value = null;
  try {
    const response = await api.changeDatabaseConnection(action, {
      ...form,
      confirm_database: confirmDatabase.value,
    });
    if (action === 'save') {
      form.revision = response.profile.revision;
      form.password_set = response.profile.password_set;
      form.password = '';
      editing.value = true;
      await load(true);
    }
    result.value = response;
    message.value =
      action === 'save'
        ? scope.value === 'platform'
          ? '已保存。请统一重启所有 Web 和调度进程后使用新平台库。'
          : '业务连接已保存，任务下次建立连接时生效。'
        : action === 'initialize'
          ? '平台表已初始化，请测试并保存连接。'
          : '';
  } catch (err) {
    error.value = err.message;
  } finally {
    busy.value = '';
  }
}
async function initialize() {
  if (confirmDatabase.value !== form.database) return;
  const yes = await props.confirm({
    title: '初始化平台数据库',
    message: `将在 ${form.host} / ${form.database} 创建平台表。`,
    details: [
      '仅支持没有平台表的新库；此操作不搬迁旧库数据。',
      'MySQL 建表会立即提交；若中途失败，需要核对已创建的表。',
    ],
    confirmText: '初始化平台表',
    danger: true,
  });
  if (yes) await run('initialize');
}
onMounted(() => load());
</script>
<style scoped>
.connection-current {
  display: grid;
  gap: 8px;
  margin-bottom: 0;
  overflow-wrap: anywhere;
}
.connection-tabs,
.connection-profiles {
  margin: 0;
}
.connection-panel .panel-body {
  gap: 16px;
}
.connection-current p,
.connection-panel .panel-body > p {
  margin: 0;
}
.connection-form fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.connection-form .filter-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 20px;
}
.connection-form .disclosure {
  margin: 24px 0;
}
.connection-form small {
  line-height: 1.6;
}
@media (max-width: 760px) {
  .connection-form .filter-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
