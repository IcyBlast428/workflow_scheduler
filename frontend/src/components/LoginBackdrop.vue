<template>
  <div ref="backdrop" class="login-backdrop" :class="{ 'is-paused': paused }" aria-hidden="true">
    <div class="login-glow login-glow-teal" />
    <div class="login-glow login-glow-gold" />
    <div class="login-plane" :style="planeStyle()">
    <div ref="gridLayer" class="login-grid" />
    <div ref="worldLayer" class="login-world">
    <svg v-for="tile in scene.tiles" :key="tile.row" :data-world-row="tile.row" class="login-network" :style="{ top: `${tile.row * scene.height}px` }" :viewBox="`0 0 ${scene.width} ${scene.height}`" fill="none" preserveAspectRatio="xMidYMid meet">
      <g v-for="(clock, index) in tile.scene.clocks" :key="index" :data-clock-id="index" class="network-clock" :transform="`translate(${clock.x} ${clock.y}) scale(${clock.scale})`">
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
        <path v-for="(route, index) in tile.scene.routes" :key="index" :d="route.path" />
      </g>
      <g class="network-packets">
        <g v-for="(packet, index) in tile.scene.packets" :key="packet.key" :style="packetStyle(packet)" :data-route-id="packet.key" :data-from="packet.source" :data-to="packet.target" :data-hops="packet.hops">
          <path class="packet-halo" :d="packet.path" />
          <path class="packet-tail" :d="packet.path" />
          <path class="packet-head" :d="packet.path" />
        </g>
      </g>
      <g class="network-junctions"><circle v-for="(point, index) in tile.scene.junctions" :key="index" :cx="point.x" :cy="point.y" r="2.5" /></g>
      <g v-for="(node, index) in tile.scene.nodes" :key="index" :transform="`translate(${node.x} ${node.y})`" class="network-node" :class="{ 'network-node-gold': node.gold }">
        <rect :x="-node.radius" :y="-node.radius" :width="node.radius * 2" :height="node.radius * 2" rx="7" />
        <rect x="-4" y="-4" width="8" height="8" rx="2" />
      </g>
      <g class="network-node-signals">
        <g v-for="(packet, index) in tile.scene.packets" :key="packet.key" :data-route-id="packet.key" :style="packetStyle(packet)">
          <g v-for="end in ['source', 'target']" :key="end" :class="['node-signal', `node-signal-${end}`, { 'network-node-gold': packet[`${end}Node`].gold }]"
            :transform="`translate(${packet[`${end}Node`].x} ${packet[`${end}Node`].y})`"
            @animationend="finishSignal($event, end, tile.row, index, packet.key)">
            <rect v-if="packet[`${end}Node`].radius" class="node-signal-rim" :x="-packet[`${end}Node`].radius" :y="-packet[`${end}Node`].radius"
              :width="packet[`${end}Node`].radius * 2" :height="packet[`${end}Node`].radius * 2" rx="7" />
            <circle v-else class="node-signal-rim" r="6" />
            <rect class="node-signal-core" x="-4" y="-4" width="8" height="8" rx="2" />
          </g>
        </g>
      </g>
    </svg>
    </div>
    </div>
    <div class="login-background-caption"><span /> WORKFLOW / TIME / EXECUTION</div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue';
import { createLoginTravelScene, advanceLoginTravelScene, createLoginPacket, createVisibleLoginPacket, refreshLoginVisiblePackets, loginPacketNodeTiming, LOGIN_CAMERA_SPEED, LOGIN_FLOW_CHECK_INTERVAL, LOGIN_NODE_CHARGE_TIME, LOGIN_NODE_SETTLE_TIME } from '../loginBackdropScene';

const seed = Math.floor(Math.random() * 4294967296);
const props = defineProps({ snapshot: { type: Object, default: null } });
const emit = defineEmits(['scene-change']);
const backdrop = ref(null);
const worldLayer = ref(null);
const gridLayer = ref(null);
const generatedScene = shallowRef(props.snapshot?.scene ?? createLoginTravelScene(1440, 960, seed));
const localPaused = ref(false);
const scene = computed(() => props.snapshot?.scene ?? generatedScene.value);
const paused = computed(() => props.snapshot?.paused ?? localPaused.value);
// The glass sample and the page subscribe to one camera. Its position is plain
// state, so advancing the camera never re-renders every SVG node through Vue.
const motion = props.snapshot?.motion ?? {
  offset: 0, elapsed: 0, listeners: new Set(),
  subscribe(listener) { this.listeners.add(listener); listener(this.offset); return () => this.listeners.delete(listener); },
  publish() { for (const listener of this.listeners) listener(this.offset); },
};
if (!props.snapshot) watch([generatedScene, localPaused], () => emit('scene-change', { scene: generatedScene.value, paused: localPaused.value, motion }), { immediate: true });
let observer;
let resizeFrame = 0;
let packetSequence = 0;
let animationSyncFrame = 0;
let cameraFrame = 0;
let previousCameraTime = null;
let reducedMotion;
let unsubscribeCamera;
let nextFlowCheck = 0;
function journeyKey() { return `${seed}:journey:${packetSequence++}`; }
function refreshFlow() {
  generatedScene.value = refreshLoginVisiblePackets(generatedScene.value, motion.offset, motion.elapsed, Math.random, journeyKey);
  nextFlowCheck = motion.elapsed + LOGIN_FLOW_CHECK_INTERVAL;
}
function animationKey(animation) {
  const target = animation.effect?.target;
  if (!target) return '';
  const packet = target.closest('[data-route-id]');
  const clock = target.closest('[data-clock-id]');
  const row = target.closest('[data-world-row]')?.dataset.worldRow;
  return `${row}:${animation.animationName}:${target.getAttribute('class')}:${packet?.dataset.routeId ?? clock?.dataset.clockId}`;
}
function syncOpticalAnimations() {
  if (!props.snapshot) return;
  cancelAnimationFrame(animationSyncFrame);
  animationSyncFrame = requestAnimationFrame(() => {
    animationSyncFrame = 0;
    const owner = backdrop.value?.closest('.login-screen')?.querySelector(':scope > .login-backdrop');
    if (!owner || !backdrop.value?.getAnimations) return;
    // Both sides of the pane must sample the same instant, including a journey
    // already in progress when the lens mounts. No per-frame animation loop.
    const originals = new Map(owner.getAnimations({ subtree: true }).map(animation => [animationKey(animation), animation]));
    for (const copy of backdrop.value.getAnimations({ subtree: true })) {
      const original = originals.get(animationKey(copy));
      if (!original) continue;
      if (original.startTime !== null) copy.startTime = original.startTime;
      else copy.currentTime = original.currentTime;
    }
  });
}
watch(() => props.snapshot, syncOpticalAnimations, { flush: 'post' });
function planeStyle() {
  const { width, height, camera } = scene.value;
  return {
    width: `${width}px`, height: `${height}px`,
    left: `${(camera.width - width) / 2}px`, top: `${(camera.height - height) / 2}px`,
    transform: `perspective(${camera.distance}px) rotateX(${camera.angle}deg)`,
  };
}
function packetStyle(packet) {
  const timing = loginPacketNodeTiming(packet);
  return {
    '--packet-delay': `${packet.delay + LOGIN_NODE_CHARGE_TIME}s`, '--packet-duration': `${packet.flowDuration}s`,
    '--node-charge-delay': `${packet.delay}s`, '--node-charge-time': `${LOGIN_NODE_CHARGE_TIME}s`,
    '--node-release-time': `${timing.sourceRelease}s`,
    '--node-arrival-delay': `${packet.delay + LOGIN_NODE_CHARGE_TIME + timing.targetArrival}s`,
    '--node-receive-time': `${timing.targetReceive}s`,
    '--node-settle-delay': `${packet.delay + LOGIN_NODE_CHARGE_TIME + packet.flowDuration}s`,
    '--node-settle-time': `${LOGIN_NODE_SETTLE_TIME}s`,
    '--packet-distance': `${-packet.travel}px`,
    '--packet-head': `${packet.head}px`, '--packet-head-gap': `${packet.period - packet.head}px`,
    '--packet-tail': `${packet.tail}px`, '--packet-tail-gap': `${packet.period - packet.tail}px`,
    '--packet-trail-offset': `${packet.tail - packet.head}px`,
  };
}
function finishSignal(event, end, row, index, key) {
  if (end === 'target' && event.animationName.startsWith('node-dim')) advancePacket(row, index, key);
}
function advancePacket(row, index, key) {
  if (props.snapshot) return; // The optical copy follows the owner's journeys.
  const current = scene.value;
  const tile = current.tiles.find(tile => tile.row === row);
  if (!tile || tile.scene.packets[index]?.key !== key) return;
  const next = createVisibleLoginPacket(current, tile, motion.offset, motion.elapsed, Math.random, journeyKey()) ??
    createLoginPacket(tile.scene, Math.random, { key: journeyKey(), startedAt: motion.elapsed });
  generatedScene.value = { ...current, tiles: current.tiles.map(item => item !== tile ? item :
    { ...item, scene: { ...item.scene, packets: item.scene.packets.map((packet, slot) => slot === index ? next : packet) } }) };
}
function stepCamera(now) {
  if (previousCameraTime !== null) {
    // A backgrounded tab never jumps ahead when it returns to the foreground.
    const delta = Math.max(0, now - previousCameraTime) / 1000;
    motion.elapsed += delta;
    motion.offset += Math.min(.1, delta) * LOGIN_CAMERA_SPEED;
    motion.publish();
    generatedScene.value = advanceLoginTravelScene(generatedScene.value, motion.offset, seed, motion.elapsed);
    if (motion.elapsed >= nextFlowCheck) refreshFlow();
  }
  previousCameraTime = now;
  cameraFrame = requestAnimationFrame(stepCamera);
}
function syncVisibility() {
  localPaused.value = document.hidden;
  cancelAnimationFrame(cameraFrame);
  previousCameraTime = null;
  cameraFrame = 0;
  if (!document.hidden && !reducedMotion?.matches) cameraFrame = requestAnimationFrame(stepCamera);
}
function resizeScene(width, height) {
  if (scene.value.camera.width === Math.round(width) && scene.value.camera.height === Math.round(height)) return;
  const newHeight = Math.round(Math.max(1, Math.round(height)) * 2.4);
  motion.offset = motion.offset / generatedScene.value.height * newHeight;
  generatedScene.value = createLoginTravelScene(width, height, seed, motion.offset, motion.elapsed);
  refreshFlow();
  motion.publish();
}
onMounted(() => {
  unsubscribeCamera = motion.subscribe(offset => {
    if (worldLayer.value) worldLayer.value.style.transform = `translateY(${offset}px)`;
    const gridSize = scene.value.camera.width <= 560 ? 44 : 64;
    if (gridLayer.value) gridLayer.value.style.transform = `translateY(${offset % gridSize}px)`;
  });
  if (props.snapshot) { syncOpticalAnimations(); return; }
  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  reducedMotion.addEventListener('change', syncVisibility);
  syncVisibility();
  document.addEventListener('visibilitychange', syncVisibility);
  const bounds = backdrop.value.getBoundingClientRect();
  resizeScene(bounds.width, bounds.height);
  refreshFlow();
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
  cancelAnimationFrame(animationSyncFrame);
  cancelAnimationFrame(cameraFrame);
  reducedMotion?.removeEventListener('change', syncVisibility);
  unsubscribeCamera?.();
});
</script>

<style scoped>
.login-backdrop { --packet-color:var(--brand-strong); --packet-core:var(--login-packet-core); position:absolute; inset:0; overflow:hidden; pointer-events:none; color:var(--brand); }
.login-glow { position:absolute; inset:0; background-repeat:no-repeat; }
.login-glow-teal { opacity:.22; background-image:radial-gradient(ellipse 65% 78% at 0% 0%, currentColor, transparent 78%); }
.login-glow-gold { color:var(--warning); opacity:.12; background-image:radial-gradient(ellipse 60% 74% at 100% 100%, currentColor, transparent 78%); }
.login-plane { position:absolute; transform-origin:center center; overflow:hidden; }
.login-world { position:absolute; inset:0; will-change:transform; }
.login-grid { position:absolute; inset:-64px; opacity:.09; background-image:linear-gradient(var(--brand) 1px,transparent 1px),linear-gradient(90deg,var(--brand) 1px,transparent 1px); background-size:64px 64px; will-change:transform; }
.login-network { position:absolute; left:0; width:100%; height:100%; overflow:hidden; }
.network-orbit { stroke:currentColor; stroke-width:1; opacity:.19; }
.network-orbit-inner { stroke-dasharray:2 13; opacity:.33; animation:clock-orbit 100s linear infinite; }
.network-orbit-core { stroke-dasharray:180 24 60 446; opacity:.22; animation:clock-orbit 80s linear infinite reverse; }
.network-ticks { stroke:currentColor; opacity:.37; stroke-width:1.5; }
.network-clock-hand { stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; opacity:.38; }
.network-clock-hub { fill:currentColor; opacity:.48; }
.network-routes { stroke:currentColor; stroke-width:2.4; stroke-linecap:round; opacity:.32; }
.network-junctions { fill:currentColor; opacity:.3; }
.network-packets path { stroke-linecap:round; animation:packet-flow var(--packet-duration) linear both; animation-delay:var(--packet-delay); }
.packet-head { stroke:var(--packet-core); stroke-width:3; stroke-dasharray:var(--packet-head) var(--packet-head-gap); opacity:.98; }
.network-packets .packet-tail, .network-packets .packet-halo { stroke:var(--packet-color); stroke-dasharray:var(--packet-tail) var(--packet-tail-gap); animation-name:packet-trail; }
.packet-tail { stroke-width:2.5; opacity:.6; }
.packet-halo { stroke-width:9; opacity:.14; }
.network-node rect:first-child { fill:var(--bg); stroke:currentColor; opacity:.48; }
.network-node rect:last-child { fill:currentColor; opacity:.55; }
.network-node-gold { color:var(--warning); }
.node-signal { opacity:0; }
.node-signal-source { animation:node-brighten var(--node-charge-time) ease-out var(--node-charge-delay) forwards, node-dim var(--node-release-time) linear var(--packet-delay) forwards; }
.node-signal-target { animation:node-brighten var(--node-receive-time) linear var(--node-arrival-delay) forwards, node-dim var(--node-settle-time) ease-out var(--node-settle-delay) forwards; }
.node-signal-rim { stroke:currentColor; stroke-width:2; fill:currentColor; fill-opacity:.2; filter:drop-shadow(0 0 6px currentColor); }
.node-signal-core { fill:var(--packet-core); filter:drop-shadow(0 0 4px currentColor); }
.login-background-caption { position:absolute; bottom:34px; left:42px; display:flex; align-items:center; gap:12px; color:var(--muted); font:10px var(--mono); letter-spacing:3px; opacity:.65; }
.login-background-caption span { width:22px; height:1px; background:var(--brand); }
.is-paused *, .is-paused svg * { animation-play-state:paused; }
@keyframes packet-flow { from { stroke-dashoffset:0; } to { stroke-dashoffset:var(--packet-distance); } }
@keyframes packet-trail { from { stroke-dashoffset:var(--packet-trail-offset); } to { stroke-dashoffset:calc(var(--packet-trail-offset) + var(--packet-distance)); } }
@keyframes node-brighten { from { opacity:0; } to { opacity:1; } }
@keyframes node-dim { from { opacity:1; } to { opacity:0; } }
@keyframes clock-orbit { to { transform:rotate(360deg); } }
@media (max-width:980px) { .network-clock { opacity:.5; } .login-background-caption { display:none; } }
@media (max-width:560px) { .login-grid { background-size:44px 44px; } .login-network { opacity:.55; } }
@media (prefers-reduced-motion:reduce) { .login-backdrop * { animation:none !important; } }
</style>
