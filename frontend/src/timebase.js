export const BUSINESS_TIMEZONE = 'Asia/Shanghai';
export function businessDate(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: BUSINESS_TIMEZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date);
  const values = Object.fromEntries(parts.map(item => [item.type, item.value]));
  return `${values.year}-${values.month}-${values.day}`;
}
export function recentDates(days = 7, date = new Date()) {
  const end = businessDate(date);
  const start = new Date(`${end}T00:00:00+08:00`); start.setUTCDate(start.getUTCDate()-days+1);
  return { start: businessDate(start), end };
}
export function businessDateTime(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA',{timeZone:BUSINESS_TIMEZONE,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date);
  const value = Object.fromEntries(parts.map(part => [part.type,part.value]));
  return `${value.year}-${value.month}-${value.day}T${value.hour}:${value.minute}`;
}
export function timestamp(value) {
  if (!value) return NaN;
  const text = String(value).replace(' ', 'T');
  return Date.parse(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(text) ? text : `${text}+08:00`);
}
