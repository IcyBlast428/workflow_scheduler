import { reactive } from 'vue';

export function useConfirm() {
  let pendingResolve = null;
  const confirmState = reactive({
    open: false,
    title: '',
    message: '',
    details: [],
    eyebrow: '',
    confirmText: '',
    cancelText: '',
    danger: false,
  });

  function requestConfirm(options) {
    if (pendingResolve) pendingResolve(null);
    Object.assign(confirmState, {
      open: true,
      title: options.title || '确认操作',
      message: options.message || '',
      details: options.details || [],
      eyebrow: options.eyebrow || '',
      confirmText: options.confirmText || '',
      cancelText: options.cancelText || '',
      danger: Boolean(options.danger),
    });

    return new Promise((resolve) => {
      pendingResolve = resolve;
    });
  }

  function resolveConfirm(result) {
    confirmState.open = false;
    if (pendingResolve) {
      pendingResolve(result);
      pendingResolve = null;
    }
  }

  return {
    confirmState,
    requestConfirm,
    resolveConfirm,
  };
}
