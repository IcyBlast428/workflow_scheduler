<template>
  <section ref="panel" class="login-panel liquid-glass">
    <svg class="glass-filter-defs" width="0" height="0" aria-hidden="true">
      <defs>
        <filter :id="filterId" filterUnits="userSpaceOnUse" primitiveUnits="userSpaceOnUse"
          :x="-GLASS_MAP_PADDING" :y="-GLASS_MAP_PADDING" :width="size.width + GLASS_MAP_PADDING * 2" :height="size.height + GLASS_MAP_PADDING * 2" color-interpolation-filters="sRGB">
          <feImage :href="displacementMap" :x="-GLASS_MAP_PADDING" :y="-GLASS_MAP_PADDING"
            :width="size.width + GLASS_MAP_PADDING * 2" :height="size.height + GLASS_MAP_PADDING * 2" preserveAspectRatio="none" result="lens-map" />
          <feComponentTransfer in="lens-map" result="unbiased-map">
            <feFuncR type="linear" slope="1" :intercept="-.5 / 255" />
            <feFuncG type="linear" slope="1" :intercept="-.5 / 255" />
          </feComponentTransfer>
          <!-- Smooth the displacement field, keeping the background itself sharp. -->
          <feGaussianBlur in="unbiased-map" stdDeviation="0.65" result="smooth-map" />
          <feDisplacementMap in="SourceGraphic" in2="smooth-map" :scale="GLASS_DISPLACEMENT_SCALE" xChannelSelector="R" yChannelSelector="G" result="refracted" />
          <!-- Light frosting scatters the background only; controls stay crisp. -->
          <feGaussianBlur in="refracted" stdDeviation="1.7" />
        </filter>
      </defs>
    </svg>
    <div v-if="snapshot && displacementMap" class="glass-optics" aria-hidden="true" :style="{ filter: `url(#${filterId})` }">
      <div class="glass-sample" :style="sampleStyle">
        <LoginBackdrop :snapshot="snapshot" />
      </div>
    </div>
    <slot />
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import LoginBackdrop from './LoginBackdrop.vue';
import { LOGIN_CORNER_RADIUS } from '../loginBackdropScene';
import { createGlassDisplacementField, GLASS_DISPLACEMENT_SCALE, GLASS_MAP_PADDING } from '../glassOptics';

const props = defineProps({ snapshot: { type: Object, default: null } });
const panel = ref(null);
const filterId = `login-lens-${Math.random().toString(36).slice(2)}`;
const displacementMap = ref('');
const size = ref({ width: 1000, height: 500, x: 0, y: 0 });
const sampleStyle = computed(() => ({
  width: `${props.snapshot?.scene.camera.width ?? 1440}px`, height: `${props.snapshot?.scene.camera.height ?? 960}px`,
  left: `${-size.value.x}px`, top: `${-size.value.y}px`,
}));
let resizeObserver;
let measureFrame = 0;
let mapDimensions = '';
function measureLens() {
  if (!panel.value) return;
  const bounds = panel.value.getBoundingClientRect();
  const root = panel.value.closest('.login-screen').getBoundingClientRect();
  const width = panel.value.clientWidth;
  const height = panel.value.clientHeight;
  if (!width || !height) return;
  size.value = { width, height, x: bounds.left + panel.value.clientLeft - root.left, y: bounds.top + panel.value.clientTop - root.top };
  const pixelRatio = window.devicePixelRatio || 1;
  const dimensions = `${width}:${height}:${pixelRatio}`;
  if (mapDimensions === dimensions) return;
  const field = createGlassDisplacementField(width, height, LOGIN_CORNER_RADIUS, pixelRatio);
  const canvas = document.createElement('canvas');
  canvas.width = field.width;
  canvas.height = field.height;
  const context = canvas.getContext('2d');
  if (!context) return;
  context.putImageData(new ImageData(field.data, field.width, field.height), 0, 0);
  displacementMap.value = canvas.toDataURL('image/png');
  mapDimensions = dimensions;
}
function scheduleMeasure() {
  cancelAnimationFrame(measureFrame);
  measureFrame = requestAnimationFrame(() => { measureFrame = 0; measureLens(); });
}
watch(() => `${props.snapshot?.scene.camera.width}:${props.snapshot?.scene.camera.height}`, scheduleMeasure);
onMounted(() => {
  measureLens();
  resizeObserver = new ResizeObserver(scheduleMeasure);
  resizeObserver.observe(panel.value);
});
onUnmounted(() => {
  cancelAnimationFrame(measureFrame);
  resizeObserver?.disconnect();
});
</script>
