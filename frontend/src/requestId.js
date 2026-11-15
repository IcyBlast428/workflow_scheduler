// Request receipts must also work on intranet HTTP, where randomUUID is absent.
export function createRequestId() {
  const crypto = globalThis.crypto;
  if (typeof crypto?.randomUUID === 'function') {
    return crypto.randomUUID().replace(/-/g, '');
  }
  if (typeof crypto?.getRandomValues !== 'function') {
    throw new Error('当前浏览器不支持生成执行请求编号，请使用新版 Chrome 或 Edge。');
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}
