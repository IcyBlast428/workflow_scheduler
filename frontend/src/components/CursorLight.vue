<template>
  <Teleport to="body">
    <div ref="light" class="cursor-light" aria-hidden="true"><span /></div>
  </Teleport>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue';

const light = ref(null);
let frame = 0;
let enabled;
let lastMove = 0;
let previous = 0;
let x = 0;
let y = 0;
let targetX = 0;
let targetY = 0;
let visible = false;

function hide() {
  cancelAnimationFrame(frame);
  frame = 0;
  visible = false;
  if (light.value) {
    light.value.style.opacity = '0';
    light.value.classList.remove('is-visible');
  }
}

function draw(now) {
  frame = 0;
  const element = light.value;
  if (!element || !enabled.matches || document.hidden) return hide();
  const elapsed = Math.min(64, Math.max(1, now - previous));
  previous = now;
  const follow = 1 - Math.exp(-elapsed / 38);
  x += (targetX - x) * follow;
  y += (targetY - y) * follow;
  const opacity = Math.max(0, 1 - Math.max(0, now - lastMove - 350) / 500);
  element.style.transform = `translate3d(${x - 28}px, ${y - 28}px, 0)`;
  element.style.opacity = String(opacity);
  if (opacity > 0) frame = requestAnimationFrame(draw);
  else hide();
}

function move(event) {
  if (event.pointerType !== 'mouse' || !enabled.matches || document.hidden) return hide();
  targetX = event.clientX + 8;
  targetY = event.clientY + 10;
  lastMove = performance.now();
  if (!visible) {
    x = targetX;
    y = targetY;
    previous = lastMove;
    visible = true;
    light.value?.classList.add('is-visible');
  }
  if (!frame) frame = requestAnimationFrame(draw);
}

function visibility() { if (document.hidden) hide(); }

onMounted(() => {
  enabled = matchMedia('(any-hover: hover) and (any-pointer: fine) and (prefers-reduced-motion: no-preference)');
  window.addEventListener('pointermove', move, { passive: true });
  window.addEventListener('blur', hide);
  document.documentElement.addEventListener('pointerleave', hide);
  document.addEventListener('visibilitychange', visibility);
  enabled.addEventListener('change', hide);
});

onUnmounted(() => {
  hide();
  window.removeEventListener('pointermove', move);
  window.removeEventListener('blur', hide);
  document.documentElement.removeEventListener('pointerleave', hide);
  document.removeEventListener('visibilitychange', visibility);
  enabled?.removeEventListener('change', hide);
});
</script>

<style scoped>
.cursor-light {
  position: fixed;
  top: 0;
  left: 0;
  width: 56px;
  height: 56px;
  z-index: 10000;
  opacity: 0;
  pointer-events: none;
  contain: strict;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(15, 118, 110, .20) 0%, rgba(15, 118, 110, .09) 22%, rgba(15, 118, 110, .035) 44%, transparent 70%);
}
.cursor-light span {
  position: absolute;
  inset: 25px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(230, 255, 249, .85), rgba(45, 212, 191, .30) 40%, transparent 72%);
  animation: cursor-glimmer 2.4s ease-in-out infinite alternate;
  animation-play-state: paused;
}
.cursor-light.is-visible span { animation-play-state: running; }
:global(html[data-theme="dark"]) .cursor-light {
  background: radial-gradient(circle, rgba(94, 234, 212, .23) 0%, rgba(45, 212, 191, .105) 22%, rgba(45, 212, 191, .035) 44%, transparent 70%);
}
@keyframes cursor-glimmer { from { opacity: .5; transform: scale(.85); } to { opacity: .9; transform: scale(1.15); } }
@media (prefers-reduced-motion: reduce), (hover: none) { .cursor-light { display: none; } }
</style>
