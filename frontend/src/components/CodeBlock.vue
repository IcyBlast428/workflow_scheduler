<template>
  <pre
    tabindex="0"
    :aria-label="label"
  ><code class="hljs syntax-highlight" v-html="highlighted"></code></pre>
</template>
<script setup>
import { computed } from 'vue';
import { highlightCode } from '../syntaxHighlight';
const props = defineProps({
  code: { type: String, default: '' },
  language: { type: String, default: 'python' },
  label: { type: String, default: '示例代码' },
});
// highlight.js escapes source text; administrator examples are never raw HTML.
const highlighted = computed(
  () => highlightCode(props.code, props.language),
);
</script>
<style scoped>
pre {
  font: 13px/1.75 var(--mono);
  color: var(--ink);
  white-space: pre;
  tab-size: 4;
}
</style>
