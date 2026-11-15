import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { api, setToken } from '../src/api.js';
import { createRequestId } from '../src/requestId.js';

const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
const values = new Map();
globalThis.sessionStorage = {
  getItem: key => values.get(key) || null,
  setItem: (key, value) => values.set(key, value),
  removeItem: key => values.delete(key),
};
globalThis.window = { setTimeout, clearTimeout };
const idPattern = /^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/;
function useCrypto(value) {
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value });
}
try {
  for (const crypto of [webcrypto, { getRandomValues: bytes => webcrypto.getRandomValues(bytes) }]) {
    useCrypto(crypto);
    const ids = Array.from({ length: 1000 }, () => createRequestId());
    ids.forEach(id => assert.match(id, idPattern));
    assert.equal(new Set(ids).size, ids.length);
    for (const kind of ['manual', 'parameterized', 'backfill', 'trial']) {
      values.clear();
      const calls = [];
      let lose = true;
      globalThis.fetch = async (_url, options) => {
        calls.push(JSON.parse(options.body));
        if (lose) { lose = false; throw new Error('response lost'); }
        return { ok: true, headers: { get: () => 'application/json' }, json: async () => ({ code: 20000, data: { id: 'accepted' } }) };
      };
      const request = { kind, context: { business_date: '2026-01-01', parameters: { region: 'CN' } } };
      const submit = pid => kind === 'manual' ? api.callTask({ pid }) : api.submitExecutionRequest(pid, request);
      await assert.rejects(submit('task'), /无法连接/);
      await submit('task');
      assert.match(calls[0].request_id, idPattern);
      assert.equal(calls[0].request_id, calls[1].request_id);
      await submit('task');
      assert.notEqual(calls[1].request_id, calls[2].request_id);
      assert.equal(values.size, 0);
      // Failed receipts stay scoped to the task and the login session.
      lose = true;
      await assert.rejects(submit('task'), /无法连接/);
      const failed = calls.at(-1).request_id;
      await submit('another-task');
      assert.notEqual(failed, calls.at(-1).request_id);
      setToken('another-session');
      await submit('task');
      assert.notEqual(failed, calls.at(-1).request_id);
    }
  }
  useCrypto(undefined);
  assert.throws(createRequestId, /新版 Chrome 或 Edge/);
} finally {
  if (originalCrypto) Object.defineProperty(globalThis, 'crypto', originalCrypto);
  else delete globalThis.crypto;
}
console.log('HTTP and secure-context execution IDs are valid, unique and reused only for retries of the same action.');
