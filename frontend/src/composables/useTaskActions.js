import {reactive,ref} from 'vue';
import {api} from '../api.js';
import {canTrigger} from '../executionLabels.js';
export function useTaskActions({view,taskLogs,loadTasks,loadTaskLogs,markBackendHealthy,handleRequestFailure,requestConfirm,pushToast,openExecution}) {
  const pendingActions=reactive({}),retryingExecution=ref(false);
  function canCallTask(row) {
    return canTrigger(row);
  }

  function callTaskTitle(row) {
    if (row.state === 'invalid') {
      return '配置错误的任务不能手动触发';
    }
    if (!canTrigger(row)) {
      return '并发名额已满，请等待正在运行的实例结束';
    }
    if (row.state === 'pause') {
      return '暂停任务也可以手动执行一次';
    }
    if (row.state !== 'true') {
      return '任务未进入调度，也可以手动执行一次';
    }
    return '立即执行一次任务';
  }

  async function editTask(row, state) {
    if (pendingActions[row.id]) return;
    if (state === 'kill') {
      const confirmed = await requestConfirm({
        title: `强制停止任务 ${row.id}`,
        message: '该操作会终止正在运行的任务进程，并将任务加入暂停列表。',
        details: [
          `任务名称：${row.name}`,
          `组名：${row.group_name || '-'}`,
          '如果脚本正在写入数据，请确认它具备幂等或补偿能力。',
        ],
        confirmText: '强制停止',
        danger: true,
      });
      if (!confirmed) {
        return;
      }
    }
    pendingActions[row.id] = state;
    try {
      const message = await api.editTask({
        id: row.id,
        state,
      });
      markBackendHealthy('后端连接正常');
      pushToast('success', '操作成功', message);
      await loadTasks();
    } catch (error) {
      await handleRequestFailure(error, { toastTitle: '操作失败' });
    } finally {
      delete pendingActions[row.id];
    }
  }

  async function handleCallTask(row) {
    if (pendingActions[row.id]) return;
    if (!canCallTask(row)) {
      pushToast('error', '无法触发任务', callTaskTitle(row));
      return;
    }
    pendingActions[row.id] = true;
    try {
      const message = await api.callTask({ pid: row.id });
      markBackendHealthy('后端连接正常');
      pushToast('success', '任务已排队', message.message || message);
      if (message.run_id) openExecution(message.run_id);
      const refreshes = [loadTasks()];
      if (view.value === 'taskLogs' && taskLogs.params.currentPage === 1) {
        refreshes.push(loadTaskLogs(false, { silent: true }));
      }
      await Promise.all(refreshes);
    } catch (error) {
      await handleRequestFailure(error, { toastTitle: '任务触发失败' });
      if (error.code === 'HTTP_409' && await requestConfirm({title:'核对原执行请求',message:'请先查看执行记录，确认原请求是否已经执行。',details:['只在确认需要新的执行后清除原请求编号，否则再次点击会继续核对原请求。','清除后再次手动执行可能重复业务操作。'],confirmText:'已核对，允许新请求',cancelText:'继续保留原请求',danger:true})) api.discardManualRequest(row.id);
    } finally {
      delete pendingActions[row.id];
    }
  }

  async function pauseTask(row) {
    if (row.pending) {
      const confirmed = await requestConfirm({
        title: `任务 ${row.id} 正在执行`,
        message: '暂停只会移除后续调度；如果要立即停止当前进程，请选择强制停止。',
        details: [
          '选择“强制停止”会终止当前进程。',
          '选择“仅暂停”会保留当前执行；关闭窗口或选择“取消”不会执行操作。',
        ],
        confirmText: '强制停止',
        cancelText: '仅暂停',
        danger: true,
      });
      if (confirmed === null) return;
      if (confirmed) {
        editTask(row, 'kill');
        return;
      }
      editTask(row, 'pause');
      return;
    }
    editTask(row, 'pause');
  }

  async function retryExecution(record) {
    if (retryingExecution.value) return;
    const confirmed = await requestConfirm({
      title: '再次执行任务',
      message: `手动执行 ${record.pid}，会生成新的执行记录。`,
      details: [
        '请先确认上次执行是否已写入业务数据；系统不会自动重试或补跑重启前的执行。',
      ],
      confirmText: '再执行一次',
      danger: true,
    });
    if (!confirmed) return;
    retryingExecution.value = true;
    try {
      api.discardManualRequest(record.pid);
      const result = await api.callTask({ pid: record.pid });
      openExecution(result.run_id);
      await loadTasks();
    } catch (error) {
      await handleRequestFailure(error, { toastTitle: '再次执行失败' });
    } finally {
      retryingExecution.value = false;
    }
  }
  async function confirmRestore(payload) {
    const confirmed = await requestConfirm({
      title: '恢复调度配置',
      message: `将 ${payload.pid} 恢复为历史版本 ${payload.restore_version}，并生成新版本。`,
      details: ['会沿用所选版本的调度启用状态；正在执行的实例继续运行。'],
      confirmText: '恢复配置',
      danger: true,
    });
    if (!confirmed) return;
    try {
      const result = await api.restore({
        pid: payload.pid,
        version: payload.version,
        restore_version: payload.restore_version,
      });
      pushToast(
        result.application?.status === 'failed' ? 'error' : 'success',
        '配置已恢复',
        result.application?.message || '已生成新版本并应用调度。',
      );
      payload.done();
      loadTasks();
    } catch (error) {
      await handleRequestFailure(error, { toastTitle: '恢复配置失败' });
    }
  }


  return {pendingActions,retryingExecution,canCallTask,callTaskTitle,editTask,handleCallTask,pauseTask,retryExecution,confirmRestore};
}
