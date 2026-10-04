import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const guard = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const cases = [
  ['IE 8', 'Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1)', undefined, true],
  ['IE 10', 'Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.2; Trident/6.0)', 10, true],
  ['IE 11', 'Mozilla/5.0 (Windows NT 6.3; Trident/7.0; rv:11.0) like Gecko', 11, true],
  ['IE compatibility mode', 'custom enterprise agent', 7, true],
  ['Edge IE mode', 'Mozilla/5.0 (Windows NT 10.0; Trident/7.0; rv:11.0) like Gecko', 11, true],
  ['Chrome', 'Mozilla/5.0 Chrome/141.0.0.0 Safari/537.36', undefined, false],
  ['Chromium Edge', 'Mozilla/5.0 Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0', undefined, false],
  ['Firefox', 'Mozilla/5.0 Gecko/20100101 Firefox/143.0', undefined, false],
];
for (const [name, userAgent, documentMode, blocked] of cases) {
  for (const storageFailure of [false, true]) {
    const root = { className: '', style: {}, setAttribute(key, value) { this[key] = value; } };
    const context = { window: {}, navigator: { userAgent }, document: { documentMode, documentElement: root },
      localStorage: { getItem() { if (storageFailure) throw new Error('Storage unavailable'); return 'light'; } } };
    vm.runInNewContext(guard, context);
    assert.equal(context.window.__WFS_UNSUPPORTED_BROWSER__, blocked, name);
    assert.equal(root.className.includes('browser-unsupported'), blocked, name);
    if (!blocked) assert.equal(root['data-theme'], storageFailure ? 'dark' : 'light');
  }
}
assert.doesNotMatch(guard, /\b(?:let|const)\s|=>|catch\s*\{/);
assert.match(html, /请使用 Chrome 内核浏览器/);
assert.match(html, /html\.browser-unsupported #app[^}]+display: none !important/);
const main = await readFile(new URL('../src/main.js', import.meta.url), 'utf8');
assert.match(main, /if \(!window\.__WFS_UNSUPPORTED_BROWSER__\)\s*\{[\s\S]*?\.mount/);
console.log('IE versions, compatibility modes, Chromium browsers and unavailable storage: browser gate passed.');
