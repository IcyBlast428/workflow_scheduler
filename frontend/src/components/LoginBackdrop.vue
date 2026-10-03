<template>
  <div ref="backdrop" class="login-backdrop" :class="{ 'is-paused': paused }" aria-hidden="true">
    <div class="login-glow login-glow-teal" />
    <div class="login-glow login-glow-gold" />
    <div class="login-grid" />
    <svg class="login-network" :viewBox="`0 0 ${scene.width} ${scene.height}`" fill="none" preserveAspectRatio="xMidYMid meet">
      <g v-for="(clock, index) in scene.clocks" :key="index" class="network-clock" :transform="`translate(${clock.x} ${clock.y}) scale(${clock.scale})`">
        <circle r="176" class="network-orbit" />
        <circle r="146" class="network-orbit network-orbit-inner" />
        <g class="network-ticks">
          <path v-for="tick in 24" :key="tick" :transform="`rotate(${tick * 15})`" :d="tick % 6 === 0 ? 'M0 -159v14' : 'M0 -159v6'" />
        </g>
        <circle r="113" class="network-orbit network-orbit-core" />
        <path d="M0 -77V0L-46 30" class="network-clock-hand" :transform="`rotate(${clock.angle})`" />
        <circle r="5" class="network-clock-hub" />
      </g>
      <g class="network-routes">
        <path v-for="(route, index) in scene.routes" :key="index" :d="route.path" />
      </g>
      <g class="network-packets">
        <g v-for="(packet, index) in scene.packets" :key="packet.key" :style="packetStyle(packet)" :data-route-id="packet.key" :data-from="packet.source" :data-to="packet.target" :data-hops="packet.hops">
          <path class="packet-halo" :d="packet.path" />
          <path class="packet-tail" :d="packet.path" />
          <path class="packet-head" :d="packet.path" @animationend="advancePacket(index)" />
        </g>
      </g>
      <g class="network-junctions"><circle v-for="(point, index) in scene.junctions" :key="index" :cx="point.x" :cy="point.y" r="2.5" /></g>
      <g v-for="(node, index) in scene.nodes" :key="index" :transform="`translate(${node.x} ${node.y})`" class="network-node" :class="{ 'network-node-gold': node.gold }">
        <rect :x="-node.radius" :y="-node.radius" :width="node.radius * 2" :height="node.radius * 2" rx="7" />
        <rect x="-4" y="-4" width="8" height="8" rx="2" />
      </g>
      <g class="network-time-labels">
        <text v-for="time in scene.times" :key="time.label" :x="time.x - 16" :y="scene.timelineY - 18">{{ time.label }}</text>
      </g>
      <g class="network-timeline">
        <path :d="`M0 ${scene.timelineY}H${scene.width}`" />
        <path v-for="time in scene.times" :key="time.label" :d="`M${time.x} ${scene.timelineY - 6}v12`" />
      </g>
    </svg>
    <div class="login-background-caption"><span /> WORKFLOW / TIME / EXECUTION</div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, shallowRef } from 'vue';
import { createLoginBackdropScene, createLoginPacket } from '../loginBackdropScene';

const seed = Math.floor(Math.random() * 4294967296);
const backdrop = ref(null);
const scene = shallowRef(createLoginBackdropScene(1440, 960, seed));
const paused = ref(false);
let observer;
let resizeFrame = 0;
let packetSequence = 0;
function packetStyle(packet) {
  return {
    '--packet-delay': `${packet.delay}s`, '--packet-duration': `${packet.duration}s`,
    '--packet-distance': `${-packet.travel}px`,
    '--packet-head': `${packet.head}px`, '--packet-head-gap': `${packet.period - packet.head}px`,
    '--packet-tail': `${packet.tail}px`, '--packet-tail-gap': `${packet.period - packet.tail}px`,
    '--packet-trail-offset': `${packet.tail - packet.head}px`,
  };
}
function advancePacket(index) {
  const current = scene.value;
  const next = createLoginPacket(current, Math.random, { key: `${seed}:journey:${packetSequence++}` });
  scene.value = { ...current, packets: current.packets.map((packet, slot) => slot === index ? next : packet) };
}
function syncVisibility() { paused.value = document.hidden; }
function resizeScene(width, height) {
  if (scene.value.width === Math.round(width) && scene.value.height === Math.round(height)) return;
  scene.value = createLoginBackdropScene(width, height, seed);
}
onMounted(() => {
  syncVisibility();
  document.addEventListener('visibilitychange', syncVisibility);
  const bounds = backdrop.value.getBoundingClientRect();
  resizeScene(bounds.width, bounds.height);
  observer = new ResizeObserver(([entry]) => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => resizeScene(entry.contentRect.width, entry.contentRect.height));
  });
  observer.observe(backdrop.value);
});
onUnmounted(() => {
  document.removeEventListener('visibilitychange', syncVisibility);
  observer?.disconnect();
  cancelAnimationFrame(resizeFrame);
});
</script>

<style scoped>
.login-backdrop { --packet-color:var(--brand-strong); --packet-core:var(--login-packet-core); position:absolute; inset:0; overflow:hidden; pointer-events:none; color:var(--brand); }
.login-glow { position:absolute; width:70vw; height:70vw; max-width:1100px; max-height:1100px; border-radius:50%; opacity:.17; background:radial-gradient(circle, currentColor, transparent 66%); }
.login-glow-teal { left:-24%; top:-36%; }
.login-glow-gold { right:-35%; bottom:-46%; color:var(--warning); opacity:.09; }
.login-grid { position:absolute; inset:0; opacity:.12; background-image:linear-gradient(var(--brand) 1px,transparent 1px),linear-gradient(90deg,var(--brand) 1px,transparent 1px); background-size:64px 64px; mask-image:radial-gradient(ellipse at center,transparent 24%,black 100%); }
.login-network { position:absolute; inset:0; width:100%; height:100%; }
.network-orbit { stroke:currentColor; stroke-width:1; opacity:.19; }
.network-orbit-inner { stroke-dasharray:2 13; opacity:.33; animation:clock-orbit 100s linear infinite; }
.network-orbit-core { stroke-dasharray:180 24 60 446; opacity:.22; animation:clock-orbit 80s linear infinite reverse; }
.network-ticks { stroke:currentColor; opacity:.37; stroke-width:1.5; }
.network-clock-hand { stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; opacity:.38; }
.network-clock-hub { fill:currentColor; opacity:.48; }
.network-routes { stroke:currentColor; stroke-width:1.4; opacity:.21; }
.network-junctions { fill:currentColor; opacity:.3; }
.network-packets path { stroke-linecap:round; animation:packet-flow var(--packet-duration) linear both; animation-delay:var(--packet-delay); }
.packet-head { stroke:var(--packet-core); stroke-width:3; stroke-dasharray:var(--packet-head) var(--packet-head-gap); opacity:.98; }
.network-packets .packet-tail, .network-packets .packet-halo { stroke:var(--packet-color); stroke-dasharray:var(--packet-tail) var(--packet-tail-gap); animation-name:packet-trail; }
.packet-tail { stroke-width:2.5; opacity:.6; }
.packet-halo { stroke-width:9; opacity:.14; }
.network-node rect:first-child { fill:var(--bg); stroke:currentColor; opacity:.48; }
.network-node rect:last-child { fill:currentColor; opacity:.55; }
.network-node-gold { color:var(--warning); }
.network-time-labels { fill:currentColor; opacity:.42; font:11px var(--mono); letter-spacing:2px; }
.network-timeline { stroke:currentColor; opacity:.27; }
.network-timeline circle { fill:currentColor; }
.login-background-caption { position:absolute; bottom:34px; left:42px; display:flex; align-items:center; gap:12px; color:var(--muted); font:10px var(--mono); letter-spacing:3px; opacity:.65; }
.login-background-caption span { width:22px; height:1px; background:var(--brand); }
.is-paused *, .is-paused svg * { animation-play-state:paused; }
@keyframes packet-flow { from { stroke-dashoffset:0; } to { stroke-dashoffset:var(--packet-distance); } }
@keyframes packet-trail { from { stroke-dashoffset:var(--packet-trail-offset); } to { stroke-dashoffset:calc(var(--packet-trail-offset) + var(--packet-distance)); } }
@keyframes clock-orbit { to { transform:rotate(360deg); } }
@media (max-width:980px) { .network-clock { opacity:.5; } .login-background-caption { display:none; } }
@media (max-width:560px) { .login-grid { background-size:44px 44px; } .login-network { opacity:.55; } }
@media (prefers-reduced-motion:reduce) { .login-backdrop * { animation:none !important; } }
</style>
