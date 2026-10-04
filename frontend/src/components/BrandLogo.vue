<template>
  <div v-glass class="brand-mark graphic-brand" role="img" aria-label="任务调度：时钟与任务节点">
    <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient :id="`${markId}-metal`" x1="10" y1="8" x2="35" y2="38" gradientUnits="userSpaceOnUse">
          <stop stop-color="#e6fff9" /><stop offset=".5" stop-color="#99f6e4" /><stop offset="1" stop-color="#43bda9" />
        </linearGradient>
        <linearGradient :id="`${markId}-node`" x1="0" y1="0" x2="1" y2="1">
          <stop stop-color="#ffffff" /><stop offset=".5" stop-color="#d8fff3" /><stop offset="1" stop-color="#83dcca" />
        </linearGradient>
        <filter :id="`${markId}-lift`" x="-40%" y="-40%" width="180%" height="190%" color-interpolation-filters="sRGB">
          <feDropShadow dx="0" dy="1.8" stdDeviation=".9" flood-color="#000e15" flood-opacity=".7" />
        </filter>
      </defs>
      <g :filter="`url(#${markId}-lift)`">
      <path d="M22 11a13 13 0 1 0 13 13" :stroke="`url(#${markId}-metal)`" stroke-width="2.5" stroke-linecap="round" />
      <path d="M22 14v10l-6 4" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
      <path d="M29 13h10v11h-5v10" stroke="#73d7c7" stroke-width="2" stroke-linejoin="round" />
      <rect x="25" y="9" width="8" height="8" rx="2" :fill="`url(#${markId}-node)`" stroke="white" stroke-opacity=".55" stroke-width=".7" />
      <rect x="35" y="20" width="8" height="8" rx="2" fill="#5eead4" stroke="#c8fff0" stroke-opacity=".6" stroke-width=".7" />
      <rect x="30" y="31" width="10" height="10" rx="3" :fill="`url(#${markId}-node)`" stroke="white" stroke-opacity=".55" stroke-width=".7" />
      <path d="m32.5 36 1.6 1.6 3.3-3.5" stroke="#0f766e" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
      </g>
    </svg>
  </div>
</template>

<script setup>
const markId = `brand-mark-${Math.random().toString(36).slice(2)}`;
</script>
