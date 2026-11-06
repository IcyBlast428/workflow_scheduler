import {reactive,onScopeDispose} from 'vue';
import {api} from '../api.js';
import {scheduleRequest} from '../scheduleForm.js';
export function useScheduleWorkspace({markBackendHealthy,handleRequestFailure,requestConfirm,pushToast,loadTasks,loadDashboard}) {
  let scheduleLoadSeq=0,schedulePreviewSeq=0;
  onScopeDispose(()=>{scheduleLoadSeq++;schedulePreviewSeq++;});
  const scheduleDialog = reactive({
    open: false,
    loading: false,
    saving: false,
    error: '',
    preview: [],
    previewLoading: false,
    previewError: '',
    task: null,
    data: null,
  });

  async function openScheduleDialog(row) {
    const keepData =
      scheduleDialog.open &&
      scheduleDialog.task?.id === row.id &&
      scheduleDialog.data;
    const seq = ++scheduleLoadSeq;
    schedulePreviewSeq += 1;
    scheduleDialog.open = true;
    scheduleDialog.loading = true;
    scheduleDialog.saving = false;
    scheduleDialog.error = '';
    if (!keepData) scheduleDialog.preview = [];
    scheduleDialog.previewError = '';
    scheduleDialog.previewLoading = false;
    scheduleDialog.task = { ...row };
    if (!keepData) scheduleDialog.data = null;
    try {
      const data = await api.taskSchedule({
        pid: row.id,
      });
      if (seq !== scheduleLoadSeq || scheduleDialog.task?.id !== row.id) {
        return;
      }
      if (data.pid && data.pid !== row.id) {
        throw new Error(
          `后端返回 PID ${data.pid} 与当前任务 ${row.id} 不一致，请刷新页面后重试。`,
        );
      }
      scheduleDialog.task = {
        ...row,
        id: row.id,
        name: data.task_name || row.name,
        group_name: data.group_name || row.group_name || '',
        folder_name: data.folder_name || row.folder_name || '',
      };
      markBackendHealthy('后端连接正常');
      scheduleDialog.data = data;
      scheduleDialog.preview = data.preview || [];
      scheduleDialog.previewError = data.preview_error || '';
    } catch (error) {
      if (seq !== scheduleLoadSeq || scheduleDialog.task?.id !== row.id) {
        return;
      }
      scheduleDialog.error = error.message;
      await handleRequestFailure(error, { toastTitle: '调度配置加载失败' });
    } finally {
      if (seq === scheduleLoadSeq && scheduleDialog.task?.id === row.id) {
        scheduleDialog.loading = false;
      }
    }
  }

  async function closeScheduleDialog(options = {}) {
    if (scheduleDialog.saving) return;
    if (
      options.dirty &&
      !(await requestConfirm({
        eyebrow: '未保存的修改',
        title: '放弃未保存的配置？',
        message: '当前修改尚未保存。关闭后会恢复已保存的配置。',
        confirmText: '放弃修改',
        cancelText: '继续编辑',
      }))
    )
      return;
    if (scheduleDialog.saving) {
      return;
    }
    scheduleLoadSeq += 1;
    schedulePreviewSeq += 1;
    scheduleDialog.previewLoading = false;
    scheduleDialog.open = false;
  }

  async function previewSchedule(form) {
    if (!scheduleDialog.open || !scheduleDialog.task) {
      return;
    }
    const seq = ++schedulePreviewSeq;
    scheduleDialog.previewLoading = true;
    scheduleDialog.previewError = '';
    try {
      const data = await api.previewTaskSchedule(
        scheduleRequest(scheduleDialog.task.id, form),
      );
      if (seq !== schedulePreviewSeq) {
        return;
      }
      scheduleDialog.preview = data.preview || [];
    } catch (error) {
      if (seq !== schedulePreviewSeq) {
        return;
      }
      scheduleDialog.preview = [];
      scheduleDialog.previewError = error.message;
    } finally {
      if (seq === schedulePreviewSeq) {
        scheduleDialog.previewLoading = false;
      }
    }
  }

  async function saveSchedule(form) {
    if (!scheduleDialog.task || scheduleDialog.saving) {
      return;
    }
    const taskId = scheduleDialog.task.id;
    scheduleDialog.saving = true;
    scheduleDialog.error = '';
    try {
      const data = await api.updateTaskSchedule(scheduleRequest(taskId, form));
      if (scheduleDialog.task?.id !== taskId) {
        return;
      }
      if (data.pid && data.pid !== taskId) {
        throw new Error(`后端保存 PID ${data.pid} 与当前任务 ${taskId} 不一致。`);
      }
      markBackendHealthy('后端连接正常');
      scheduleDialog.data = data;
      scheduleDialog.preview = data.preview || [];
      scheduleDialog.previewError = data.preview_error || '';
      scheduleDialog.open = false;
      pushToast(
        data.application?.status === 'failed' ? 'error' : 'success',
        '任务配置已保存',
        data.application?.status === 'failed'
          ? `保存成功，但生效失败：${data.application.message}。请刷新任务重新应用。`
          : `${taskId} 已生效。`,
      );
      await Promise.all([loadTasks(), loadDashboard({ silent: true })]);
    } catch (error) {
      scheduleDialog.error = error.message;
      await handleRequestFailure(error, { toastTitle: '调度策略保存失败' });
    } finally {
      scheduleDialog.saving = false;
    }
  }


  return {scheduleDialog,openScheduleDialog,closeScheduleDialog,previewSchedule,saveSchedule};
}
