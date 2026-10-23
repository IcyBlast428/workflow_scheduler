import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import sql from 'highlight.js/lib/languages/sql';
import bash from 'highlight.js/lib/languages/bash';
import json from 'highlight.js/lib/languages/json';
import yaml from 'highlight.js/lib/languages/yaml';
import ini from 'highlight.js/lib/languages/ini';
import javascript from 'highlight.js/lib/languages/javascript';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import css from 'highlight.js/lib/languages/css';
import plaintext from 'highlight.js/lib/languages/plaintext';

for (const [name, language] of Object.entries({ python, sql, bash, json, yaml, ini, javascript, typescript, xml, css, plaintext }))
  hljs.registerLanguage(name, language);

export function languageForFilename(filename = '') {
  const name = filename.split('/').pop().toLowerCase();
  if (name === '.wfs-task.json') return 'json';
  const extension = name.split('.').pop();
  return ({ py:'python', pyw:'python', sql:'sql', sh:'bash', bash:'bash', json:'json',
    yml:'yaml', yaml:'yaml', ini:'ini', cfg:'ini', toml:'ini', js:'javascript', mjs:'javascript',
    ts:'typescript', xml:'xml', html:'xml', htm:'xml', svg:'xml', css:'css' })[extension] || 'plaintext';
}

export function highlightCode(code, language = 'plaintext') {
  // The highlighter escapes all source HTML, including unknown-language text.
  return hljs.highlight(code, { language: hljs.getLanguage(language) ? language : 'plaintext', ignoreIllegals:true }).value;
}

export function highlightCodeLines(code, language) {
  const html = highlightCode(code, language);
  const lines = [], spans = [];
  let current = '', previous = 0;
  // Close and reopen spans at line breaks so multi-line strings/comments retain
  // their highlighting across separate line elements and pagination boundaries.
  for (const match of html.matchAll(/<span\b[^>]*>|<\/span>|\n/g)) {
    current += html.slice(previous, match.index);
    const token = match[0];
    if (token === '\n') {
      lines.push(current + '</span>'.repeat(spans.length));
      current = spans.join('');
    } else {
      if (token === '</span>') spans.pop(); else spans.push(token);
      current += token;
    }
    previous = match.index + token.length;
  }
  lines.push(current + html.slice(previous));
  return lines;
}
