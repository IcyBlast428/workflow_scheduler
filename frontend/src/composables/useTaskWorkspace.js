import { api } from '../api.js';
import { reactive, ref, watch, onScopeDispose } from 'vue';
import { readPreference, writePreference } from '../workspacePreferences.js';

const defaults = () => ({
  currentPage: 1,
  pagesize: 10,
  taskid: '',
  taskname: '',
  taskgroup: '',
  status: '',
  owner: '',
});
export function useTaskWorkspace(
  identity,
  { markBackendHealthy, handleRequestFailure, requestConfirm, pushToast },
) {
  let taskRequestSerial = 0;
  onScopeDispose(() => {
    taskRequestSerial++;
  });
  const tasks = reactive({
    loading: false,
    error: '',
    items: [],
    total: 0,
    groups: [],
    params: defaults(),
  });
  const favorites = ref([]),
    onlyFavorites = ref(false),
    selectedTasks = ref([]),
    batchBusy = ref(false);
  const key = () => `wfs:tasks:${identity() || 'anonymous'}`;
  watch(
    identity,
    () => {
      taskRequestSerial++;
      tasks.items = [];
      tasks.total = 0;
      const saved = readPreference(key(), {});
      Object.assign(tasks.params, defaults());
      for (const field of Object.keys(tasks.params))
        if (['string', 'number'].includes(typeof saved.filters?.[field]))
          tasks.params[field] = saved.filters[field];
      tasks.params.currentPage = 1;
      favorites.value = Array.isArray(saved.favorites)
        ? saved.favorites.filter((id) => typeof id === 'string')
        : [];
      onlyFavorites.value = Boolean(saved.onlyFavorites);
      selectedTasks.value = [];
    },
    { immediate: true },
  );
  function saveFilters() {
    writePreference(key(), {
      filters: { ...tasks.params, currentPage: 1 },
      favorites: favorites.value,
      onlyFavorites: onlyFavorites.value,
    });
  }
  function toggleFavorite(id) {
    favorites.value = favorites.value.includes(id)
      ? favorites.value.filter((value) => value !== id)
      : [...favorites.value, id];
    saveFilters();
  }
  function toggleSelected(id) {
    selectedTasks.value = selectedTasks.value.includes(id)
      ? selectedTasks.value.filter((value) => value !== id)
      : [...selectedTasks.value, id];
  }
  async function loadGroups() {
    try {
      tasks.groups = await api.groups();
      markBackendHealthy('后端连接正常');
    } catch (error) {
      await handleRequestFailure(error, { toastTitle: '分组加载失败' });
    }
  }

  async function loadTasks(resetPage = false, options = {}) {
    const serial = ++taskRequestSerial;
    if (resetPage) {
      tasks.params.currentPage = 1;
    }
    if (!options.silent) {
      tasks.loading = true;
    }
    tasks.error = '';
    try {
      saveFilters();
      if (onlyFavorites.value && !favorites.value.length) {
        tasks.items = [];
        tasks.total = 0;
        return;
      }
      const data = await api.taskState({
        ...tasks.params,
        ids: onlyFavorites.value ? favorites.value : [],
      });
      if (serial !== taskRequestSerial) return;
      markBackendHealthy('后端连接正常');
      tasks.items = data.items || [];
      tasks.total = data.total || 0;
    } catch (error) {
      if (serial === taskRequestSerial)
        await handleRequestFailure(error, { state: tasks });
    } finally {
      if (serial === taskRequestSerial && !options.silent) {
        tasks.loading = false;
      }
    }
  }

  function resetTaskFilters() {
    tasks.params.taskid = '';
    tasks.params.taskname = '';
    tasks.params.taskgroup = '';
    tasks.params.status = '';
    tasks.params.owner = '';
    onlyFavorites.value = false;
    loadTasks(true);
  }

  function setTaskPage(page) {
    tasks.params.currentPage = page;
    loadTasks();
  }

  function setTaskPageSize(size) {
    tasks.params.pagesize = size;
    tasks.params.currentPage = 1;
    loadTasks();
  }

  async function batchTaskAction(action) {
    if (batchBusy.value) return;
    batchBusy.value = true;
    try {
      const ids = [...selectedTasks.value];
      const { preview } = await api.batch({ ids, action, preview: true });
      const label = action === 'pause' ? '暂停调度' : '启用调度';
      const confirmed = await requestConfirm({
        title: `批量${label}`,
        message: `将对 ${preview.length} 个任务${label}。`,
        details: [
          ...preview.map(
            (item) => `${item.name} (${item.pid}) · 活动 ${item.active}`,
          ),
          '正在执行的实例继续运行；本操作只改变后续调度。',
        ],
        confirmText: label,
        danger: true,
      });
      if (!confirmed) return;
      const data = await api.batch({
        ids,
        action,
        versions: Object.fromEntries(
          preview.map((item) => [item.pid, item.version]),
        ),
      });
      const failures = data.results.filter((item) => !item.ok);
      selectedTasks.value = failures.map((item) => item.pid);
      pushToast(
        failures.length ? 'error' : 'success',
        '批量操作结果',
        failures.length
          ? failures.map((item) => `${item.pid}：${item.message}`).join('；')
          : `${data.results.length} 个任务已${label}`,
      );
      await loadTasks();
    } catch (error) {
      await handleRequestFailure(error, { toastTitle: '批量操作失败' });
    } finally {
      batchBusy.value = false;
    }
  }
  return {
    loadTasks,
    loadGroups,
    resetTaskFilters,
    setTaskPage,
    setTaskPageSize,
    batchTaskAction,
    tasks,
    favorites,
    onlyFavorites,
    selectedTasks,
    batchBusy,
    saveFilters,
    toggleFavorite,
    toggleSelected,
  };
}
