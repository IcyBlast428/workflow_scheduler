import assert from 'node:assert/strict';
import { createLoginBackdropScene, createLoginPerspectiveScene, createLoginTravelScene, advanceLoginTravelScene, createLoginPacket, LOGIN_CORNER_RADIUS } from '../src/loginBackdropScene.js';

const coordinates = point => `${point.x},${point.y}`;
const curveKey = ({ from, control1, control2, to }) => [
  [from, control1, control2, to].map(coordinates).join('|'),
  [to, control2, control1, from].map(coordinates).join('|'),
].sort()[0];
function sampleCurve({ from, control1, control2, to }, t) {
  const u = 1 - t;
  return {
    x: u ** 3 * from.x + 3 * u ** 2 * t * control1.x + 3 * u * t ** 2 * control2.x + t ** 3 * to.x,
    y: u ** 3 * from.y + 3 * u ** 2 * t * control1.y + 3 * u * t ** 2 * control2.y + t ** 3 * to.y,
    dx: 3 * u ** 2 * (control1.x - from.x) + 6 * u * t * (control2.x - control1.x) + 3 * t ** 2 * (to.x - control2.x),
    dy: 3 * u ** 2 * (control1.y - from.y) + 6 * u * t * (control2.y - control1.y) + 3 * t ** 2 * (to.y - control2.y),
  };
}
function verifyJourney(scene, packet) {
  const drawnCurves = new Set(scene.routes.flatMap(route => route.curves.map(curveKey)));
  assert.notEqual(packet.source, packet.target, 'A journey must arrive at another node');
  assert.ok(scene.nodes.some(node => node.id === packet.source));
  assert.ok(scene.nodes.some(node => node.id === packet.target));
  if (scene.packetNodes) {
    assert.ok(scene.packetNodes.some(node => node.id === packet.source));
    assert.ok(scene.packetNodes.some(node => node.id === packet.target));
  }
  assert.equal(coordinates(packet.points[0]), coordinates(scene.graph.points[packet.source]));
  assert.equal(coordinates(packet.points.at(-1)), coordinates(scene.graph.points[packet.target]));
  assert.equal((packet.path.match(/M/g) || []).length, 1, 'A journey must be continuous');
  const renderedSegments = packet.path.slice(packet.path.indexOf('L') >= 0 ? packet.path.indexOf('L') : packet.path.indexOf('C'));
  assert.equal(renderedSegments, packet.curves.map(curve => curve.kind === 'line' ? `L${curve.to.x} ${curve.to.y}`
    : `C${curve.control1.x} ${curve.control1.y} ${curve.control2.x} ${curve.control2.y} ${curve.to.x} ${curve.to.y}`).join(''));
  for (let index = 0; index < packet.curves.length; index++) {
    const curve = packet.curves[index];
    assert.ok(drawnCurves.has(curveKey(curve)), 'Light must follow exactly the visible curve in either direction');
    assert.equal(coordinates(curve.from), coordinates(index ? packet.curves[index - 1].to : scene.graph.points[packet.source]),
      'Curve joins must not teleport');
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
    assert.ok(!('timelineBand' in scene) && !('times' in scene), 'No timeline lane may constrain the scatter layout');
    const reachable = new Set([0]);
    const pending = [0];
    for (let index = 0; index < pending.length; index++) {
      for (const edge of scene.graph.adjacency[pending[index]]) {
        if (!reachable.has(edge.to)) { reachable.add(edge.to); pending.push(edge.to); }
      }
    }
    assert.equal(reachable.size, scene.graph.points.length, 'Every scattered node must remain reachable');
    const typicalSpacing = Math.sqrt(width * height / scene.graph.points.length);
    for (let column = 0; column <= 10; column++) {
      for (let row = 0; row <= 10; row++) {
        const x = width * column / 10;
        const y = height * row / 10;
        const nearest = Math.min(...scene.graph.points.map(point => Math.hypot(point.x - x, point.y - y)));
        assert.ok(nearest < typicalSpacing * 1.35, `Scatter left an empty area: ${width}x${height}, seed ${seed}, at ${x},${y}, distance ${nearest}, spacing ${typicalSpacing}`);
      }
    }
    for (const route of scene.routes) {
      assert.ok(route.curves.some(curve => curve.kind === 'line'), 'Straight stretches must remain straight');
      let measuredLength = 0;
      for (const curve of route.curves) {
        if (curve.kind === 'corner') {
          assert.ok(curve.radius > 0 && curve.radius <= LOGIN_CORNER_RADIUS + 1e-9,
            'Bends use the login card radius, shortened only where space is limited');
          assert.ok(Math.abs(curve.radius - LOGIN_CORNER_RADIUS) < .001 ||
            route.points.slice(1).some((point, index) => Math.hypot(point.x - route.points[index].x, point.y - route.points[index].y) < 45),
            'Full sized corners must keep the shared radius');
        }
        let previous = curve.from;
        for (let index = 0; index <= 128; index++) {
          const point = sampleCurve(curve, index / 128);
          measuredLength += Math.hypot(point.x - previous.x, point.y - previous.y);
          previous = point;
        }
      }
      assert.ok(Math.abs(measuredLength - route.length) < Math.max(.15, measuredLength * .002),
        'Estimated arc length must retain accurate light travel speed');
    }
    for (const packet of scene.packets) verifyJourney(scene, packet);
  }
}
for (const [width, height] of [[320,240], [390,844], [1440,960], [1969,1964], [3660,1961]]) {
  const scene = createLoginPerspectiveScene(width, height, 42);
  const { camera } = scene;
  const project = (x, y) => {
    const localY = y - scene.height / 2;
    const scale = 1 / (1 - localY * Math.SQRT1_2 / camera.distance);
    return { x: width / 2 + (x - scene.width / 2) * scale,
      y: height / 2 + localY * Math.SQRT1_2 * scale, scale };
  };
  const farLeft = project(0, 0);
  const farRight = project(scene.width, 0);
  const nearLeft = project(0, scene.height);
  const nearRight = project(scene.width, scene.height);
  assert.equal(camera.angle, 45);
  assert.ok(nearLeft.scale > farLeft.scale && farLeft.scale > 0, 'Near nodes must be larger than distant nodes');
  assert.ok(farLeft.x <= 0 && farRight.x >= width && farLeft.y <= 0 && nearLeft.y >= height &&
    nearLeft.x <= 0 && nearRight.x >= width, 'The tilted plane must cover the entire viewport');
  for (const packet of scene.packets) verifyJourney(scene, packet);
}
const scene = createLoginBackdropScene(1440, 960, 42);
assert.ok(scene.packets.some(packet => packet.hops >= 4), 'Light must travel through intermediate nodes');
assert.notDeepEqual(scene.routes, createLoginBackdropScene(1440, 960, 43).routes);
assert.deepEqual(scene.routes, createLoginBackdropScene(1440, 960, 42).routes);
const journeys = Array.from({ length: 30 }, (_, index) => createLoginPacket(scene, Math.random, { key: `next:${index}` }));
for (const packet of journeys) verifyJourney(scene, packet);
assert.ok(new Set(journeys.map(packet => `${packet.source}:${packet.target}`)).size > 1);

for (const [width, height] of [[390,844], [1440,960], [3660,1961]]) {
  let world = createLoginTravelScene(width, height, 42);
  assert.equal(advanceLoginTravelScene(world, world.height * .9, 42), world, 'Camera movement must not regenerate stationary world geometry');
  for (const cycle of [1, 2, 3, 1000]) {
    const survivor = world.tiles[0];
    const beforeBoundary = cycle * world.height - .001;
    const afterBoundary = cycle * world.height + .001;
    world = advanceLoginTravelScene(world, afterBoundary, 42);
    assert.equal(world.tiles.length, 2, 'The advancing world must retain bounded rendering and memory');
    assert.deepEqual(world.tiles[0].bottomPorts, world.tiles[1].topPorts, 'Neighbouring networks must share exact wire ports');
    if (cycle < 1000) {
      assert.equal(world.tiles[1], survivor, 'Existing nodes, wires and light journeys must survive a refill');
      const point = survivor.scene.nodes[0];
      const oldY = survivor.row * world.height + point.y + beforeBoundary;
      const newY = world.tiles[1].row * world.height + point.y + afterBoundary;
      assert.ok(Math.abs(newY - oldY - .002) < 1e-6, 'Refilling must not reset the camera or teleport the scene');
    }
    for (const tile of world.tiles) {
      for (const packet of tile.scene.packets) verifyJourney(tile.scene, packet);
      for (const x of tile.topPorts) {
        const route = tile.scene.routes.find(route => route.points[0].x === x && route.points[0].y === 0);
        assert.ok(route, 'The far wire must connect to the next section');
        assert.equal(route.curves[0].from.x, route.curves[0].to.x, 'A seam must have a vertical tangent');
      }
      for (const x of tile.bottomPorts) {
        const route = tile.scene.routes.find(route => route.points.at(-1).x === x && route.points.at(-1).y === world.height);
        assert.ok(route, 'The near wire must connect to the previous section');
        assert.equal(route.curves.at(-1).from.x, route.curves.at(-1).to.x, 'Both sides of a seam must have the same tangent');
      }
    }
  }
}
console.log('Login backdrop: uniform random coverage, connected rounded wires, multi-node light, perspective and continuous bounded camera travel passed.');
