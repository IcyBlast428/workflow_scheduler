<template>
  <pre
    tabindex="0"
    :aria-label="label"
  ><code class="hljs" v-html="highlighted"></code></pre>
</template>
<script setup>
import { computed } from 'vue';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import sql from 'highlight.js/lib/languages/sql';
import bash from 'highlight.js/lib/languages/bash';
import json from 'highlight.js/lib/languages/json';
import plaintext from 'highlight.js/lib/languages/plaintext';
for (const [name, language] of Object.entries({
  python,
  sql,
  bash,
  json,
  plaintext,
}))
  hljs.registerLanguage(name, language);
const props = defineProps({
  code: { type: String, default: '' },
  language: { type: String, default: 'python' },
  label: { type: String, default: '示例代码' },
});
// highlight.js escapes source text; administrator examples are never raw HTML.
const highlighted = computed(
  () =>
    hljs.highlight(props.code, {
      language: hljs.getLanguage(props.language) ? props.language : 'plaintext',
      ignoreIllegals: true,
    }).value,
);
</script>
<style scoped>
pre {
  font: 13px/1.75 var(--mono);
  color: var(--ink);
  white-space: pre;
  tab-size: 4;
}
.hljs :deep(.hljs-keyword),
.hljs :deep(.hljs-literal) {
  color: #c4a1ff;
}
.hljs :deep(.hljs-string),
.hljs :deep(.hljs-doctag) {
  color: #a7dca0;
}
.hljs :deep(.hljs-comment) {
  color: #90a4b8;
  font-style: italic;
}
.hljs :deep(.hljs-title),
.hljs :deep(.hljs-built_in) {
  color: #74c9ed;
}
.hljs :deep(.hljs-number),
.hljs :deep(.hljs-attr) {
  color: #edc58d;
}
.hljs :deep(.hljs-subst),
.hljs :deep(.hljs-params) {
  color: var(--ink);
}
</style>
