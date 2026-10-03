import assert from 'node:assert/strict';
import { createLoginTravelScene, advanceLoginTravelScene, refreshLoginVisiblePackets, loginPacketVisible,
  createLoginPacket, loginPacketNodeTiming, loginVisibleFlowTarget,
  LOGIN_CAMERA_SPEED, LOGIN_PACKET_SPEED, LOGIN_FLOW_CHECK_INTERVAL, LOGIN_NODE_CHARGE_TIME, LOGIN_NODE_SETTLE_TIME } from '../src/loginBackdropScene.js';

assert.ok(LOGIN_PACKET_SPEED * .85 >= LOGIN_CAMERA_SPEED * 10, 'Even the slowest flow must visibly outrun the advancing camera');
let state = 123456;
const random = () => ((state = (Math.imul(state, 1664525) + 1013904223) >>> 0) / 4294967296);
let key = 0;
const timingScene = createLoginTravelScene(1440, 960, 42).tiles[1].scene;
const journeys = Array.from({ length: 60 }, (_, index) => createLoginPacket(timingScene, random, { key: `timing:${index}` }));
const speeds = journeys.map(packet => packet.speed);
assert.ok(Math.max(...speeds) / Math.min(...speeds) > 2, 'Independent journeys should have visibly different speeds');
for (const packet of journeys) {
  const timing = loginPacketNodeTiming(packet);
  assert.ok(Math.abs(timing.sourceRelease * packet.speed - (packet.tail - packet.head)) < 1e-8,
    'Source must return to its resting state when the trailing light clears it');
  assert.ok(Math.abs(timing.targetArrival * packet.speed + packet.head - packet.length) < 1e-8,
    'Destination must start lighting when the leading light reaches it');
  assert.ok(Math.abs(timing.targetArrival + timing.targetReceive - packet.flowDuration) < 1e-8,
    'Destination must complete its receipt before quickly fading');
  assert.ok(Math.abs(packet.duration - LOGIN_NODE_CHARGE_TIME - packet.flowDuration - LOGIN_NODE_SETTLE_TIME) < 1e-8,
    'Journey replacement must wait for the destination to fade');
}
for (const [width, height] of [[390,844], [1440,960], [3232,1964]]) {
  for (const seed of [7, 42, 95]) {
    for (const phase of [0, .48, .93]) {
      let world = createLoginTravelScene(width, height, seed);
      assert.equal(loginVisibleFlowTarget(world), width < 600 ? 1 : width * height > 3000000 ? 3 : 2, 'Visible flow target should be half the previous density');
      assert.ok(world.tiles.every(tile => tile.scene.packets.length <= (width < 600 ? 2 : width * height > 3000000 ? 6 : 4)), 'Initial packet pools should also be halved');
      const initialOffset = world.height * phase;
      let nextCheck = 0;
      // Sample every 100ms, including the boundary where a new section enters.
      for (let tick = 0; tick < 1200; tick++) {
        const elapsed = tick / 10;
        const offset = initialOffset + elapsed * LOGIN_CAMERA_SPEED;
        world = advanceLoginTravelScene(world, offset, seed, elapsed);
        if (elapsed + 1e-6 >= nextCheck) {
          world = refreshLoginVisiblePackets(world, offset, elapsed, random, () => `test:${key++}`);
          nextCheck = elapsed + LOGIN_FLOW_CHECK_INTERVAL;
        }
        const visible = world.tiles.reduce((total, tile) => total + tile.scene.packets.filter(packet =>
          loginPacketVisible(world, tile, packet, offset, elapsed)).length, 0);
        assert.ok(visible > 0, `No visible flow: ${width}x${height}, seed ${seed}, phase ${phase}, time ${elapsed}`);
        assert.ok(world.tiles.every(tile => tile.scene.packets.length <= 18), 'Off-screen replacement must not accumulate an unlimited number of lights');
      }
    }
  }
}
console.log('Login flow: no empty visible interval across 120s camera journeys, refills, view sizes and seeds; packet pools stay bounded.');
