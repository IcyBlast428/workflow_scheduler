<template>
  <section class="panel connection-panel">
    <div class="panel-head">
      <div>
        <h2>数据库连接</h2>
        <p>管理平台数据库与任务业务数据库，任务只需使用连接标识。</p>
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
          {{ profile.id }} · {{ typeLabel(profile.dialect) }}</button
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
      <section
        v-if="scope === 'business'"
        class="database-support"
        aria-label="支持的数据库"
      >
        <strong>支持的数据库</strong>
        <div class="filter-actions">
          <span
            v-for="item in databaseTypes"
            :key="item.dialect"
            class="tag"
            :class="item.available ? 'success' : 'info'"
            :title="item.package"
            >{{ item.label }} ·
            {{ item.available ? '驱动就绪' : '需安装驱动' }}</span
          >
        </div>
        <p class="hint">
          数据库类型由连接标识对应的配置自动选择；除 MySQL、SQLite
          外，其余类型需在目标数据库上验收。SQL Server 还需系统 ODBC 驱动。
        </p>
      </section>
      <form class="connection-form" @submit.prevent="run('save')">
        <fieldset :disabled="busy || loading">
          <div class="filter-grid">
            <div v-if="scope === 'business'" class="form-row connection-wide">
              <label for="db-type">数据库类型</label
              ><select
                id="db-type"
                v-model="form.dialect"
                class="select"
                @change="typeChanged"
              >
                <option
                  v-for="item in databaseTypes"
                  :key="item.dialect"
                  :value="item.dialect"
                >
                  {{ item.label }}
                </option></select
              ><small class="hint"
                >{{ selectedType?.package
                }}{{
                  selectedType?.available === false
                    ? ' · 当前服务器尚未具备完整驱动'
                    : ''
                }}</small
              >
            </div>
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
            <div v-if="!isSQLite" class="form-row">
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
            <div v-if="!isSQLite" class="form-row">
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
              <label for="db-name">{{
                isSQLite
                  ? 'SQLite 文件名'
                  : form.dialect === 'oracle'
                    ? 'Oracle 服务名'
                    : '数据库名称'
              }}</label
              ><input
                id="db-name"
                v-model.trim="form.database"
                class="input"
                required
                maxlength="64"
                :placeholder="
                  isSQLite ? '例如 reports.sqlite3' : '例如 workflow_scheduler'
                "
              />
              <small v-if="isSQLite" class="hint"
                >文件保存在服务数据目录 business-databases 下。</small
              >
            </div>
            <div v-if="!isSQLite" class="form-row">
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
            <div v-if="!isSQLite" class="form-row">
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
            <div v-if="!isSQLite" class="form-row">
              <label for="db-tls">连接加密</label
              ><select id="db-tls" v-model="form.tls" class="select">
                <option value="verify_identity">TLS（校验证书和主机名）</option>
                <option value="disabled">不使用 TLS</option>
              </select>
            </div>
            <div
              v-if="
                !isSQLite &&
                form.tls === 'verify_identity' &&
                form.dialect !== 'mssql'
              "
              class="form-row"
            >
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
            <div
              v-if="form.dialect === 'mssql'"
              class="form-row connection-wide"
            >
              <label for="db-odbc">SQL Server ODBC 驱动名称</label
              ><input
                id="db-odbc"
                v-model.trim="form.odbc_driver"
                class="input"
                required
              /><small class="hint"
                >启用 TLS 时使用操作系统证书信任库，并校验服务器证书。</small
              >
            </div>
          </div>
          <details v-if="scope === 'business'" class="disclosure pool-options">
            <summary>连接池设置</summary>
            <p class="hint">
              同一进程按连接标识共享连接池，关闭 NewDB
              会归还连接。不同任务子进程不共享连接池。
            </p>
            <label class="checkbox-row"
              ><input
                v-model="form.pool_enabled"
                type="checkbox"
              />启用连接池</label
            >
            <div v-if="form.pool_enabled" class="filter-grid">
              <div class="form-row">
                <label for="db-pool-size">常驻连接上限</label
                ><input
                  id="db-pool-size"
                  v-model.number="form.pool_size"
                  type="number"
                  class="input"
                  min="1"
                  max="20"
                  required
                />
              </div>
              <div class="form-row">
                <label for="db-pool-overflow">临时额外连接上限</label
                ><input
                  id="db-pool-overflow"
                  v-model.number="form.max_overflow"
                  type="number"
                  class="input"
                  min="0"
                  max="20"
                  required
                />
              </div>
              <div class="form-row">
                <label for="db-pool-recycle">连接回收周期（秒）</label
                ><input
                  id="db-pool-recycle"
                  v-model.number="form.pool_recycle"
                  type="number"
                  class="input"
                  min="30"
                  max="3600"
                  required
                />
              </div>
              <div class="form-row">
                <label for="db-pool-timeout">等待空闲连接（秒）</label
                ><input
                  id="db-pool-timeout"
                  v-model.number="form.pool_timeout"
                  type="number"
                  class="input"
                  min="1"
                  max="120"
                  required
                />
              </div>
            </div>
          </details>
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
  dialect: 'mysql',
  id: '',
  host: '',
  port: 3306,
  database: '',
  user: '',
  password: '',
  password_set: false,
  tls: 'disabled',
  ssl_ca: '',
  revision: 0,
  pool_enabled: true,
  pool_size: 3,
  max_overflow: 2,
  pool_recycle: 600,
  pool_timeout: 10,
  odbc_driver: 'ODBC Driver 18 for SQL Server',
});
const form = reactive(empty());
const databaseTypes = computed(
  () =>
    state.value.supported_databases || [
      {
        dialect: 'mysql',
        label: 'MySQL / PolarDB / MariaDB',
        port: 3306,
        available: true,
        package: 'PyMySQL',
      },
    ],
);
const selectedType = computed(() =>
  databaseTypes.value.find((item) => item.dialect === form.dialect),
);
const isSQLite = computed(() => form.dialect === 'sqlite');
function typeLabel(dialect) {
  return (
    databaseTypes.value.find((item) => item.dialect === (dialect || 'mysql'))
      ?.label || dialect
  );
}
function typeChanged() {
  form.port = selectedType.value?.port || 3306;
  form.tls = 'disabled';
  form.ssl_ca = '';
}
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
.connection-form .form-row {
  grid-template-rows: 20px 40px auto;
  align-content: start;
  gap: 8px;
}
.connection-form .form-row label {
  align-self: start;
  line-height: 20px;
}
.connection-form .input,
.connection-form .select {
  height: 40px;
  min-height: 40px;
  align-self: start;
  box-sizing: border-box;
}
.connection-form .form-row small {
  margin: 0;
  line-height: 18px;
}
.connection-wide {
  grid-column: 1 / -1;
}
.database-support {
  display: grid;
  gap: 10px;
}
.database-support p {
  margin: 0;
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
