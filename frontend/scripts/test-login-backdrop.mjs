import assert from 'node:assert/strict';
import { createLoginBackdropScene, createLoginPacket } from '../src/loginBackdropScene.js';

const coordinates = point => `${point.x},${point.y}`;
const segment = (from, to) => [coordinates(from), coordinates(to)].sort().join('|');
function verifyJourney(scene, packet) {
  const drawnSegments = new Set(scene.routes.flatMap(route => route.points.slice(1).map((point, index) => segment(route.points[index], point))));
  assert.notEqual(packet.source, packet.target, 'A journey must arrive at another node');
  assert.ok(scene.nodes.some(node => node.id === packet.source));
  assert.ok(scene.nodes.some(node => node.id === packet.target));
  assert.equal(coordinates(packet.points[0]), coordinates(scene.graph.points[packet.source]));
  assert.equal(coordinates(packet.points.at(-1)), coordinates(scene.graph.points[packet.target]));
  assert.equal((packet.path.match(/M/g) || []).length, 1, 'A journey must be continuous');
  const renderedPoints = [...packet.path.matchAll(/[ML](-?[\d.]+) (-?[\d.]+)/g)].map(match => `${match[1]},${match[2]}`);
  assert.deepEqual(renderedPoints, packet.points.map(coordinates));
  for (let index = 1; index < packet.points.length; index++) {
    assert.ok(drawnSegments.has(segment(packet.points[index - 1], packet.points[index])), 'Light must follow a visible wire');
  }
  for (let index = 1; index < packet.nodeIds.length; index++) {
    assert.ok(scene.graph.adjacency[packet.nodeIds[index - 1]].some(edge => edge.to === packet.nodeIds[index]));
  }
  assert.ok(packet.period > packet.travel + packet.head, 'The head must not wrap back to the source at arrival');
  assert.ok(Number.isFinite(packet.duration) && packet.duration > 0);
}

for (const [width, height] of [[320,240], [390,844], [1440,960], [1969,1964], [3660,1961]]) {
  for (let seed = 1; seed <= 20; seed++) {
    const scene = createLoginBackdropScene(width, height, seed);
    assert.ok(scene.nodes.length >= 2, 'Even a small screen needs two eligible endpoints');
    for (const node of scene.nodes) {
      assert.ok(node.y + node.radius < scene.timelineBand.top || node.y - node.radius > scene.timelineBand.bottom,
        'Task nodes must leave space around the time labels');
    }
    for (const route of scene.routes) {
      for (let index = 1; index < route.points.length; index++) {
        const from = route.points[index - 1];
        const to = route.points[index];
        const nearlyHorizontal = Math.abs(to.y - from.y) < Math.abs(to.x - from.x) * .7;
        assert.ok(!nearlyHorizontal || Math.max(from.y, to.y) < scene.timelineBand.top || Math.min(from.y, to.y) > scene.timelineBand.bottom,
          'Nearly horizontal wires must stay outside the timeline lane');
      }
    }
    for (const packet of scene.packets) verifyJourney(scene, packet);
  }
}
const scene = createLoginBackdropScene(1440, 960, 42);
assert.ok(scene.packets.some(packet => packet.hops >= 4), 'Light must travel through intermediate nodes');
assert.notDeepEqual(scene.routes, createLoginBackdropScene(1440, 960, 43).routes);
assert.deepEqual(scene.routes, createLoginBackdropScene(1440, 960, 42).routes);
const journeys = Array.from({ length: 30 }, (_, index) => createLoginPacket(scene, Math.random, { key: `next:${index}` }));
for (const packet of journeys) verifyJourney(scene, packet);
assert.ok(new Set(journeys.map(packet => `${packet.source}:${packet.target}`)).size > 1);
console.log('Login backdrop: connected multi-node journeys, renewed endpoints and responsive layouts passed.');
