<template><!-- Illumination is painted inside the glass backgrounds. --></template>

<script setup>
import { onMounted, onUnmounted } from 'vue';

const glassSelector = '.glass-surface, .topbar, .metric-card, .matrix-camera-bar, .liquid-glass, .user-chip, .sidebar, .nav-button, .graphic-brand';
let frame = 0;
let enabled;
let transparency;
let radiusX = 190;
let radiusY = 150;
const surfaces = new Set();
let pointer = null;

function clearSurfaces() {
  for (const surface of surfaces) surface.style.removeProperty('--glass-pointer-opacity');
  surfaces.clear();
}

function hide() {
  cancelAnimationFrame(frame);
  frame = 0;
  pointer = null;
  clearSurfaces();
}

function draw() {
  frame = 0;
  if (document.documentElement.dataset.effects === 'low' || !pointer || !enabled.matches || transparency.matches || document.hidden) return hide();
  // A dialog's backdrop shields the workspace behind it from the pointer light.
  const scope = document.elementFromPoint(pointer.x, pointer.y)?.closest('.modal-backdrop') || document;
  const illuminated = new Set();
  for (const surface of scope.querySelectorAll(glassSelector)) {
    const bounds = surface.getBoundingClientRect();
    if (!bounds.width || !bounds.height || bounds.bottom <= 0 || bounds.right <= 0
      || bounds.top >= window.innerHeight || bounds.left >= window.innerWidth) continue;
    const dx = Math.max(bounds.left - pointer.x, 0, pointer.x - bounds.right);
    const dy = Math.max(bounds.top - pointer.y, 0, pointer.y - bounds.bottom);
    // Keep the light centred on the actual pointer, even outside the glass.
    // The same ellipse as the CSS gradient naturally fades at its outer edge.
    if ((dx / radiusX) ** 2 + (dy / radiusY) ** 2 >= 1) continue;
    illuminated.add(surface);
    surface.style.setProperty('--glass-pointer-x', `${pointer.x - bounds.left - surface.clientLeft}px`);
    surface.style.setProperty('--glass-pointer-y', `${pointer.y - bounds.top - surface.clientTop}px`);
    surface.style.setProperty('--glass-pointer-opacity', '1');
  }
  for (const surface of surfaces) {
    if (!illuminated.has(surface)) surface.style.removeProperty('--glass-pointer-opacity');
  }
  surfaces.clear();
  for (const surface of illuminated) surfaces.add(surface);
}

function schedule() {
  if (pointer && !frame) frame = requestAnimationFrame(draw);
}

function move(event) {
  if (document.documentElement.dataset.effects === 'low' || event.pointerType !== 'mouse' || !enabled.matches || transparency.matches || document.hidden) return hide();
  pointer = { x: event.clientX, y: event.clientY };
  schedule();
}

function visibility() { if (document.hidden) hide(); }

onMounted(() => {
  const styles = getComputedStyle(document.documentElement);
  radiusX = parseFloat(styles.getPropertyValue('--glass-pointer-radius-x')) || radiusX;
  radiusY = parseFloat(styles.getPropertyValue('--glass-pointer-radius-y')) || radiusY;
  enabled = matchMedia('(any-hover: hover) and (any-pointer: fine) and (prefers-reduced-motion: no-preference)');
  transparency = matchMedia('(prefers-reduced-transparency: reduce)');
  window.addEventListener('pointermove', move, { passive: true });
  window.addEventListener('pointerdown', move, { passive: true });
  window.addEventListener('scroll', schedule, { passive: true, capture: true });
  window.addEventListener('resize', schedule, { passive: true });
  window.addEventListener('blur', hide);
  window.addEventListener('wfs:effects',hide);
  document.documentElement.addEventListener('pointerleave', hide);
  document.addEventListener('visibilitychange', visibility);
  enabled.addEventListener('change', hide);
  transparency.addEventListener('change', hide);
});

onUnmounted(() => {
  hide();
  window.removeEventListener('pointermove', move);
  window.removeEventListener('pointerdown', move);
  window.removeEventListener('scroll', schedule, true);
  window.removeEventListener('resize', schedule);
  window.removeEventListener('blur', hide);
  window.removeEventListener('wfs:effects',hide);
  document.documentElement.removeEventListener('pointerleave', hide);
  document.removeEventListener('visibilitychange', visibility);
  enabled?.removeEventListener('change', hide);
  transparency?.removeEventListener('change', hide);
});
</script>
