<template>
  <details class="repository-settings surface-card" @toggle="opened">
    <summary>任务依赖仓库 <span class="hint">Nexus / 离线安装</span></summary>
    <div class="repository-content">
      <p class="hint">
        设置只用于准备新任务版本的环境。已发布版本继续复用原环境；任务运行时不会重复安装依赖。
      </p>
      <p v-if="loading" role="status">正在读取仓库设置…</p>
      <div v-if="error" class="inline-alert danger" role="alert">
        {{ error }}
        <button v-if="!loaded" class="btn" @click="load">重试</button>
      </div>
      <p v-if="message" class="inline-alert success" role="status">
        {{ message }}
      </p>
      <form v-if="loaded" @submit.prevent="save">
        <fieldset :disabled="saving">
          <div class="filter-grid">
            <div class="form-row">
              <label for="pip-mode">依赖安装方式</label
              ><select id="pip-mode" v-model="form.mode" class="select">
                <option value="nexus">Nexus 私有仓库</option>
                <option value="offline">离线 wheels</option>
              </select>
            </div>
            <div class="form-row">
              <label for="pip-index">Nexus pip 索引地址</label
              ><input
                id="pip-index"
                v-model.trim="form.index_url"
                class="input"
                type="url"
                required
                maxlength="1000"
                placeholder="http://nexus.immp.icbc/repository/pypi-hosted/simple/"
              /><small class="hint">地址未带 /simple/ 时自动补全。</small>
            </div>
            <div class="form-row">
              <label for="pip-user">仓库认证账号（可选）</label
              ><input
                id="pip-user"
                v-model.trim="form.username"
                class="input"
                autocomplete="off"
                maxlength="100"
              /><small class="hint"
                >当前提供的 Nexus 无需认证，保持为空。</small
              >
            </div>
            <div class="form-row">
              <label for="pip-password">仓库认证密码（可选）</label
              ><input
                id="pip-password"
                v-model="form.password"
                class="input"
                type="password"
                autocomplete="new-password"
                maxlength="1024"
                :placeholder="
                  form.password_set ? '已设置，留空保留' : '无需认证时留空'
                "
              />
            </div>
            <div class="form-row">
              <label for="pip-ca">HTTPS 内部 CA 路径（可选）</label
              ><input
                id="pip-ca"
                v-model.trim="form.ca_bundle"
                class="input"
                maxlength="1024"
                placeholder="HTTP 仓库无需填写"
              />
            </div>
          </div>
          <p class="hint">
            Nexus
            模式只使用此索引，并自动解析间接依赖；离线模式要求所有依赖精确锁定并上传
            wheels。两种模式均安装匹配当前 Python / 系统的 wheel。
          </p>
          <button class="btn primary">
            {{ saving ? '保存中…' : '保存仓库设置' }}
          </button>
        </fieldset>
      </form>
    </div>
  </details>
</template>
<script setup>
import { reactive, ref } from 'vue';
import { api } from '../api';
const form = reactive({}),
  loaded = ref(false),
  loading = ref(false),
  saving = ref(false),
  error = ref(''),
  message = ref('');
function opened(event) {
  if (event.target.open && !loaded.value && !loading.value) load();
}
async function load() {
  loading.value = true;
  error.value = '';
  try {
    Object.assign(form, await api.packageRepository(), { password: '' });
    loaded.value = true;
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}
async function save() {
  if (saving.value) return;
  saving.value = true;
  error.value = '';
  message.value = '';
  try {
    Object.assign(form, await api.savePackageRepository({ ...form }), {
      password: '',
    });
    message.value = '仓库设置已保存，新版本检查依赖时生效。';
  } catch (err) {
    error.value = err.message;
  } finally {
    saving.value = false;
  }
}
</script>
<style scoped>
.repository-settings {
  min-width: 0;
}
summary {
  cursor: pointer;
  font-weight: 600;
  line-height: 1.7;
}
summary .hint {
  font-weight: 400;
  margin-left: 12px;
}
.repository-content {
  display: grid;
  gap: 16px;
  margin-top: 16px;
}
fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.filter-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.form-row {
  grid-template-rows: 20px 40px auto;
  align-content: start;
  gap: 8px;
}
.form-row label {
  line-height: 20px;
}
.form-row .input,
.form-row .select {
  height: 40px;
  min-height: 40px;
  box-sizing: border-box;
}
.form-row .hint {
  margin: 0;
  line-height: 18px;
}
.repository-content p {
  line-height: 1.8;
  margin: 0;
}
form .hint {
  margin: 16px 0;
}
@media (max-width: 760px) {
  .filter-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
