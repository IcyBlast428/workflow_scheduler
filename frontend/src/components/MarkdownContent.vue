<template>
  <div v-if="content.trim()" class="markdown-content" v-html="rendered"></div>
  <p v-else class="hint">暂未填写任务说明。</p>
</template>
<script setup>
import { computed } from 'vue';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { highlightCode } from '../syntaxHighlight';

const props = defineProps({ content: { type: String, default: '' } });
const renderer = new marked.Renderer();
renderer.code = ({ text, lang }) => `<pre><code class="syntax-highlight">${highlightCode(text, (lang || '').split(/\s/)[0])}</code></pre>`;
// Raw HTML stays readable as text, so authors cannot reuse application CSS classes.
renderer.html = ({ text }) => highlightCode(text, 'plaintext');
const rendered = computed(() => DOMPurify.sanitize(marked.parse(props.content, { renderer, gfm: true, breaks: true }), {
  // Task authors cannot inject controls, styles, media requests or executable HTML.
  ALLOWED_TAGS: ['p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'strong', 'em', 'del', 'blockquote', 'pre', 'code', 'span', 'a', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td'],
  ALLOWED_ATTR: ['href', 'title', 'class', 'start'],
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
  // Allow useful external references, but no script, data or custom app protocols.
  ALLOWED_URI_REGEXP: /^(?:https?:\/\/|mailto:)/i,
}));
</script>
<style scoped>
.markdown-content{max-width:78ch;color:var(--ink);font-size:14px;line-height:1.85;overflow-wrap:anywhere}
.markdown-content :deep(:first-child){margin-top:0}
.markdown-content :deep(:last-child){margin-bottom:0}
.markdown-content :deep(h1){font-size:22px}.markdown-content :deep(h2){font-size:19px}.markdown-content :deep(h3){font-size:16px}
.markdown-content :deep(h1),.markdown-content :deep(h2),.markdown-content :deep(h3),.markdown-content :deep(h4){line-height:1.5;margin:22px 0 10px}
.markdown-content :deep(p){margin:10px 0}.markdown-content :deep(ul),.markdown-content :deep(ol){padding-left:24px;margin:10px 0}
.markdown-content :deep(li){margin:4px 0}.markdown-content :deep(blockquote){margin:16px 0;padding:4px 16px;border-left:3px solid var(--brand);color:var(--muted);background:var(--brand-soft)}
.markdown-content :deep(code){font:13px/1.75 var(--mono);background:var(--brand-soft);padding:2px 5px;border-radius:4px}
.markdown-content :deep(pre){max-width:100%;overflow:auto;padding:16px;background:var(--panel-soft);border:1px solid var(--line);border-radius:8px;white-space:pre}
.markdown-content :deep(pre code){background:none;padding:0}.markdown-content :deep(a){color:var(--brand);text-decoration:underline;text-underline-offset:3px}
.markdown-content :deep(table){display:block;max-width:100%;overflow:auto;border-collapse:collapse}.markdown-content :deep(th),.markdown-content :deep(td){padding:8px 12px;border:1px solid var(--line)}
.markdown-content :deep(hr){border:0;border-top:1px solid var(--line);margin:18px 0}
</style>
