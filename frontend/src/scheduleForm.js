// A reused dialog must keep only editable fields belonging to the current task.
export function resetScheduleForm(target, defaults, source = {}) {
  for (const key of Object.keys(target)) delete target[key];
  for (const key of Object.keys(defaults)) {
    const value = Object.hasOwn(source, key) ? source[key] : defaults[key];
    target[key] = Array.isArray(value) ? [...value] : value;
  }
}

export function scheduleRequest(pid, form) {
  // Task identity comes from the dialog owner, never from saved JSON or form fields.
  return { ...form, pid };
}
