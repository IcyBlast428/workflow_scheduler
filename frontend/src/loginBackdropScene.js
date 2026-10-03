// App.vue also exposes this as --login-radius for the login card.
export const LOGIN_CORNER_RADIUS = 20;
export const LOGIN_CAMERA_SPEED = 10; // World pixels per second, before perspective.
export const LOGIN_PACKET_SPEED = 135;
export const LOGIN_FLOW_CHECK_INTERVAL = .25;
export const LOGIN_NODE_CHARGE_TIME = .12;
export const LOGIN_NODE_SETTLE_TIME = .18;

// A page keeps its seed while resizing; a fresh page creates a new arrangement.
function randomFromSeed(seed) {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = Math.imul(state ^ (state >>> 15), state | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function pathFromCurves(curves) {
  const start = curves[0].from;
  return `M${start.x} ${start.y}` + curves.map(({ kind, control1, control2, to }) => kind === 'line'
    ? `L${to.x} ${to.y}` : `C${control1.x} ${control1.y} ${control2.x} ${control2.y} ${to.x} ${to.y}`).join('');
}

function curveLength({ kind, from, control1, control2, to }) {
  if (kind === 'line') return Math.hypot(to.x - from.x, to.y - from.y);
  let previous = from;
  let length = 0;
  // Arc length keeps the light's speed consistent on both straight and bowed routes.
  for (let index = 1; index <= 32; index++) {
    const t = index / 32;
    const u = 1 - t;
    const point = {
      x: u ** 3 * from.x + 3 * u ** 2 * t * control1.x + 3 * u * t ** 2 * control2.x + t ** 3 * to.x,
      y: u ** 3 * from.y + 3 * u ** 2 * t * control1.y + 3 * u * t ** 2 * control2.y + t ** 3 * to.y,
    };
    length += Math.hypot(point.x - previous.x, point.y - previous.y);
    previous = point;
  }
  return length;
}

function reverseCurves(curves) {
  return [...curves].reverse().map(curve =>
    ({ ...curve, from: curve.to, control1: curve.control2, control2: curve.control1, to: curve.from }));
}

function roundedPolyline(vertices, radius) {
  const curves = [];
  const mix = (from, to, t) => ({ x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t });
  let cursor = vertices[0];
  const lineTo = to => {
    if (Math.hypot(to.x - cursor.x, to.y - cursor.y) < .001) return;
    curves.push({ kind: 'line', from: cursor, control1: mix(cursor, to, 1 / 3), control2: mix(cursor, to, 2 / 3), to });
    cursor = to;
  };
  for (let index = 1; index < vertices.length - 1; index++) {
    const previous = vertices[index - 1];
    const corner = vertices[index];
    const next = vertices[index + 1];
    const incoming = Math.hypot(corner.x - previous.x, corner.y - previous.y);
    const outgoing = Math.hypot(next.x - corner.x, next.y - corner.y);
    if (Math.min(incoming, outgoing) < .001) continue;
    const u = { x: (corner.x - previous.x) / incoming, y: (corner.y - previous.y) / incoming };
    const v = { x: (next.x - corner.x) / outgoing, y: (next.y - corner.y) / outgoing };
    const angle = Math.acos(Math.max(-1, Math.min(1, u.x * v.x + u.y * v.y)));
    if (angle < .001 || angle > Math.PI - .001) { lineTo(corner); continue; }
    const trim = Math.min(radius * Math.tan(angle / 2), incoming * .45, outgoing * .45);
    const actualRadius = trim / Math.tan(angle / 2);
    const handle = 4 / 3 * Math.tan(angle / 4) * actualRadius;
    const entry = { x: corner.x - u.x * trim, y: corner.y - u.y * trim };
    const exit = { x: corner.x + v.x * trim, y: corner.y + v.y * trim };
    lineTo(entry);
    curves.push({ kind: 'corner', radius: actualRadius, from: entry,
      control1: { x: entry.x + u.x * handle, y: entry.y + u.y * handle },
      control2: { x: exit.x - v.x * handle, y: exit.y - v.y * handle }, to: exit });
    cursor = exit;
  }
  lineTo(vertices.at(-1));
  return curves;
}

function shuffled(items, random) {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index--) {
    const other = Math.floor(random() * (index + 1));
    [result[index], result[other]] = [result[other], result[index]];
  }
  return result;
}

// Route a whole journey over the connected network, including intermediate nodes.
export function createLoginPacket(scene, random = Math.random, { key = '', stagger = false, startedAt = 0, allowedIds = null } = {}) {
  const endpoints = scene.packetNodes ?? scene.nodes;
  const source = endpoints[Math.floor(random() * endpoints.length)].id;
  const parents = Array(scene.graph.points.length).fill(null);
  const distances = Array(scene.graph.points.length).fill(-1);
  const queue = [source];
  distances[source] = 0;
  for (let index = 0; index < queue.length; index++) {
    const from = queue[index];
    for (const edge of shuffled(scene.graph.adjacency[from], random)) {
      if (distances[edge.to] !== -1 || (allowedIds && !allowedIds.has(edge.to))) continue;
      parents[edge.to] = { from, edge };
      distances[edge.to] = distances[from] + 1;
      queue.push(edge.to);
    }
  }
  let targets = endpoints.filter(node => node.id !== source && distances[node.id] > 0);
  if (!targets.length) return null;
  // Most journeys are long; all distinct endpoint pairs remain eligible.
  if (random() < .85) {
    const minimum = Math.min(scene.preferredHops, Math.max(...targets.map(node => distances[node.id])));
    targets = targets.filter(node => distances[node.id] >= minimum);
  }
  const target = targets[Math.floor(random() * targets.length)].id;
  const steps = [];
  let cursor = target;
  while (cursor !== source) {
    const previous = parents[cursor];
    steps.push(previous.edge);
    cursor = previous.from;
  }
  steps.reverse();
  const points = [scene.graph.points[source]];
  const curves = [];
  const nodeIds = [source];
  for (const step of steps) {
    points.push(...step.points.slice(1));
    curves.push(...step.curves);
    nodeIds.push(step.to);
  }
  const length = steps.reduce((total, step) => total + step.length, 0);
  const head = Math.min(14, length * .15);
  const tail = Math.min(112, length * .4);
  const travel = length + tail;
  const period = travel + tail + head;
  // Each journey keeps its own speed: a broad range reads as independent work.
  const speed = LOGIN_PACKET_SPEED * (.85 + random() * 1.5);
  const flowDuration = travel / speed;
  const duration = LOGIN_NODE_CHARGE_TIME + flowDuration + LOGIN_NODE_SETTLE_TIME;
  return {
    key, path: pathFromCurves(curves), points, curves, nodeIds, source, target, hops: steps.length,
    length, travel, period, head, tail, speed, flowDuration, duration, startedAt,
    sourceNode: scene.nodes.find(node => node.id === source) ?? scene.graph.points[source],
    targetNode: scene.nodes.find(node => node.id === target) ?? scene.graph.points[target],
    delay: stagger ? -random() * duration : random() * .8,
  };
}

export function createLoginBackdropScene(width, height, seed, options = {}) {
  width = Math.max(1, Math.round(width));
  height = Math.max(1, Math.round(height));
  const random = randomFromSeed(seed);
  const round = value => Math.round(value);
  const between = (start, end) => start + random() * (end - start);
  const spacingScale = options.spacingScale ?? 1;
  const columns = Math.min(18, Math.max(2, Math.ceil(width / (330 * spacingScale))));
  const rows = Math.min(12, Math.max(2, Math.ceil(height / (270 * spacingScale))));
  const cellWidth = width / columns;
  const cellHeight = height / rows;
  const points = [];
  const nodes = [];
  const junctions = [];
  const routes = [];

  // Best-candidate blue-noise scatter fills the largest available gaps without
  // aligning nodes to rows or columns. Keep the same overall node density.
  for (let index = 0; index < rows * columns; index++) {
    let point;
    let bestDistance = -1;
    for (let attempt = 0; attempt < 24; attempt++) {
      // Seed the four outer regions so a short or narrow section cannot leave
      // an entire corner empty; the remaining points fill gaps freely.
      const candidate = index < 4 ? {
        id: index,
        x: round(index % 2 ? width - cellWidth * between(.3, .7) : cellWidth * between(.3, .7)),
        y: round(index >= 2 ? height - cellHeight * between(.3, .7) : cellHeight * between(.3, .7)),
      } : { id: index, x: round(between(width * .015, width * .985)), y: round(between(height * .015, height * .985)) };
      const distance = points.reduce((nearest, other) => Math.min(nearest, (other.x - candidate.x) ** 2 + (other.y - candidate.y) ** 2), Infinity);
      if (distance > bestDistance) { point = candidate; bestDistance = distance; }
      if (!points.length) break;
    }
    points.push(point);
    if (random() < .52 || index % 5 === 0 || index === rows * columns - 1) {
      nodes.push({ ...point, gold: random() < .2, radius: round(between(10, 14)) });
    } else {
      junctions.push(point);
    }
  }

  const graph = { points, adjacency: Array.from({ length: points.length }, () => []) };
  const minimumBend = Math.min(38, cellWidth * .15, cellHeight * .15);
  const connect = (from, to, edge = false, suppliedVertices = null) => {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const ax = Math.abs(dx);
    const ay = Math.abs(dy);
    const vertices = suppliedVertices ?? [from];
    // Retain irregular straight routes without small corrective zigzags.
    if (!suppliedVertices && Math.min(ax, ay) >= minimumBend && Math.abs(ax - ay) >= minimumBend) {
      if (random() < .65) {
        const diagonalFirst = random() < .5;
        vertices.push(ax >= ay
          ? (diagonalFirst ? { x: from.x + Math.sign(dx) * ay, y: to.y } : { x: to.x - Math.sign(dx) * ay, y: from.y })
          : (diagonalFirst ? { x: to.x, y: from.y + Math.sign(dy) * ax } : { x: from.x, y: to.y - Math.sign(dy) * ax }));
      } else {
        vertices.push(random() < .5 ? { x: to.x, y: from.y } : { x: from.x, y: to.y });
      }
    }
    if (!suppliedVertices) vertices.push(to);
    const curves = roundedPolyline(vertices, LOGIN_CORNER_RADIUS);
    const length = curves.reduce((total, curve) => total + curveLength(curve), 0);
    routes.push({ path: pathFromCurves(curves), points: vertices, curves, length, edge });
    if (!edge) {
      graph.adjacency[from.id].push({ to: to.id, points: vertices, curves, length });
      graph.adjacency[to.id].push({ to: from.id, points: [...vertices].reverse(), curves: reverseCurves(curves), length });
    }
  };

  // A minimum spanning tree keeps every scattered node reachable using short
  // local wires. A few local loops provide alternative routes for the light.
  const connected = new Set([0]);
  const closest = points.map(point => ({ from: 0, distance: Math.hypot(point.x - points[0].x, point.y - points[0].y) }));
  while (connected.size < points.length) {
    let next = -1;
    for (const point of points) {
      if (!connected.has(point.id) && (next === -1 || closest[point.id].distance < closest[next].distance)) next = point.id;
    }
    connect(points[closest[next].from], points[next]);
    connected.add(next);
    for (const point of points) {
      const distance = Math.hypot(point.x - points[next].x, point.y - points[next].y);
      if (!connected.has(point.id) && distance < closest[point.id].distance) closest[point.id] = { from: next, distance };
    }
  }
  for (const point of points) {
    if (random() > .25) continue;
    const neighbours = points.filter(other => other.id !== point.id)
      .sort((a, b) => Math.hypot(a.x - point.x, a.y - point.y) - Math.hypot(b.x - point.x, b.y - point.y)).slice(0, 3)
      .filter(other => !graph.adjacency[point.id].some(edge => edge.to === other.id));
    if (neighbours.length) connect(point, neighbours[Math.floor(random() * neighbours.length)]);
  }

  // Ports run to the page edges, including the corners of very wide screens.
  const nearest = (x, y) => points.reduce((best, point) =>
    Math.hypot(point.x - x, point.y - y) < Math.hypot(best.x - x, best.y - y) ? point : best);
  if (options.topPorts && options.bottomPorts) {
    // Neighbouring world sections share exact ports and vertical tangents.
    // The joining edge stays connected while the camera passes the seam.
    for (const x of options.topPorts) {
      const top = nearest(x, 0);
      connect({ x, y: 0 }, top, true, [{ x, y: 0 }, { x, y: Math.min(60, top.y / 2) }, top]);
    }
    for (const x of options.bottomPorts) {
      const bottom = nearest(x, height);
      connect(bottom, { x, y: height }, true, [bottom, { x, y: height - Math.min(60, (height - bottom.y) / 2) }, { x, y: height }]);
    }
  } else {
    for (let column = 0; column < columns; column += 2) {
      const top = nearest((column + .5) * cellWidth, 0);
      const bottom = nearest((column + .5) * cellWidth, height);
      connect({ x: top.x, y: -12 }, top, true);
      connect(bottom, { x: bottom.x, y: height + 12 }, true);
    }
  }
  for (let row = 0; row < rows; row += 2) {
    const left = nearest(0, (row + .5) * cellHeight);
    const right = nearest(width, (row + .5) * cellHeight);
    connect({ x: -12, y: left.y }, left, true);
    connect(right, { x: width + 12, y: right.y }, true);
  }

  const sideSpace = Math.max(120, (width - Math.min(1000, width - 48)) / 2);
  const radius = round(Math.min(172, sideSpace * .65, height * .23));
  const rightSide = random() < .5;
  const clockX = between(sideSpace * .3, sideSpace * .7);
  const clockY = (clockRadius, low, high) => round(Math.min(height - clockRadius - 12, between(low, high) * height));
  const clocks = [{
    x: round(rightSide ? width - clockX : clockX), y: clockY(radius, .26, .74),
    scale: radius / 176, angle: round(between(0, 360)),
  }];
  if (width > 2200 || (width > 1100 && height > 1300)) {
    const otherX = between(sideSpace * .3, sideSpace * .7);
    clocks.push({ x: round(rightSide ? otherX : width - otherX), y: clockY(radius * .55, .2, .8), scale: radius * .55 / 176, angle: round(between(0, 360)) });
  }

  const scene = { width, height, nodes, junctions, routes, graph, clocks, preferredHops: Math.min(7, Math.max(3, Math.floor((rows + columns) / 2))) };
  const packetCount = options.packetCount ?? (width < 600 ? 2 : width * height > 3000000 ? 6 : 4);
  scene.packets = Array.from({ length: packetCount }, (_, index) => createLoginPacket(scene, random, { key: `${width}:${height}:initial:${index}`, stagger: true }));
  return scene;
}

export function createLoginPerspectiveScene(viewportWidth, viewportHeight, seed, options = {}) {
  const width = Math.max(1, Math.round(viewportWidth));
  const height = Math.max(1, Math.round(viewportHeight));
  const camera = { width, height, distance: Math.max(width, height) * 1.6, angle: 45 };
  const planeWidth = width * 2;
  const planeHeight = Math.round(height * 2.4);
  const sin = Math.SQRT1_2;
  const cos = Math.SQRT1_2;
  // Inverse of CSS perspective(distance) rotateX(45deg). The oversized plane
  // covers all four screen corners, including the distant edge on tall phones.
  const unproject = (x, y) => {
    const localY = (y - height / 2) / (cos + (y - height / 2) * sin / camera.distance);
    const scale = 1 / (1 - localY * sin / camera.distance);
    return { x: planeWidth / 2 + (x - width / 2) / scale, y: planeHeight / 2 + localY, scale };
  };
  const random = randomFromSeed(seed ^ 0x17c5a3);
  const scene = createLoginBackdropScene(planeWidth, planeHeight, seed, {
    ...options, spacingScale: options.spacingScale ?? (width < 600 ? .8 : 1.1), packetCount: 0,
  });
  scene.camera = camera;
  scene.cornerRadius = LOGIN_CORNER_RADIUS;
  const sideSpace = Math.max(120, (width - Math.min(1000, width - 48)) / 2);
  const radius = Math.min(172, sideSpace * .65, height * .23);
  scene.clocks = scene.clocks.slice(0, width > 2200 ? 2 : 1).map((clock, index) => {
    const right = (seed % 2 === 0) !== (index === 1);
    const center = unproject(right ? width - sideSpace * .55 : sideSpace * .55, height * (.38 + random() * .32));
    const clockRadius = radius * (index ? .55 : 1);
    return { ...clock, x: center.x, y: center.y, scale: clockRadius / (176 * center.scale) };
  });
  // Overscan nodes cover the page edges, but journeys should start and finish
  // at visible task nodes rather than spending their whole life off screen.
  const visibleNodes = scene.nodes.filter(node => {
    const localY = node.y - planeHeight / 2;
    const scale = 1 / (1 - localY * sin / camera.distance);
    const x = width / 2 + (node.x - planeWidth / 2) * scale;
    const y = height / 2 + localY * cos * scale;
    return x > 0 && x < width && y > 0 && y < height;
  });
  scene.packetNodes = visibleNodes.length >= 2 ? visibleNodes : scene.nodes;
  const packetCount = width < 600 ? 2 : width * height > 3000000 ? 6 : 4;
  scene.packets = Array.from({ length: packetCount }, (_, index) =>
    createLoginPacket(scene, random, { key: `${width}:${height}:initial:${index}`, stagger: true }));
  return scene;
}

function worldSeed(seed, row) { return (seed ^ Math.imul(row, 0x45d9f3b)) >>> 0; }
function worldPorts(width, seed, boundary) {
  const random = randomFromSeed(worldSeed(seed ^ 0x318fa2, boundary));
  const count = Math.max(2, Math.min(8, Math.ceil(width / 720)));
  return Array.from({ length: count }, (_, index) => Math.round(width * (index + .2 + random() * .6) / count));
}
function createWorldTile(world, row, seed, original = null, elapsed = 0) {
  const topPorts = worldPorts(world.width, seed, row);
  const bottomPorts = worldPorts(world.width, seed, row + 1);
  const scene = original ?? createLoginBackdropScene(world.width, world.height, worldSeed(seed, row), {
    topPorts, bottomPorts, spacingScale: world.camera.width < 600 ? .8 : 1.1,
    packetCount: world.camera.width < 600 ? 2 : world.camera.width * world.camera.height > 3000000 ? 6 : 4,
  });
  scene.packets = scene.packets.map(packet => ({ ...packet, startedAt: elapsed }));
  return { row, scene, topPorts, bottomPorts };
}

export function createLoginTravelScene(width, height, seed, offset = 0, elapsed = 0) {
  const planeWidth = Math.max(1, Math.round(width)) * 2;
  const original = createLoginPerspectiveScene(width, height, seed, {
    topPorts: worldPorts(planeWidth, seed, 0), bottomPorts: worldPorts(planeWidth, seed, 1),
  });
  const world = { width: original.width, height: original.height, camera: original.camera, tiles: [] };
  const step = Math.floor(Math.max(0, offset) / world.height);
  world.tiles = [-step - 1, -step].map(row => createWorldTile(world, row, seed, row === 0 ? original : null, elapsed));
  return world;
}

export function advanceLoginTravelScene(world, offset, seed, elapsed = 0) {
  const step = Math.floor(Math.max(0, offset) / world.height);
  const rows = [-step - 1, -step];
  if (world.tiles.every((tile, index) => tile.row === rows[index])) return world;
  return { ...world, tiles: rows.map(row => world.tiles.find(tile => tile.row === row) ?? createWorldTile(world, row, seed, null, elapsed)) };
}

export function projectLoginWorldPoint(world, row, point, offset) {
  const planeY = row * world.height + point.y + offset;
  if (planeY < 0 || planeY > world.height) return null;
  const localY = planeY - world.height / 2;
  const scale = 1 / (1 - localY * Math.SQRT1_2 / world.camera.distance);
  return { x: world.camera.width / 2 + (point.x - world.width / 2) * scale,
    y: world.camera.height / 2 + localY * Math.SQRT1_2 * scale };
}
function inViewport(world, point, inset = 0) {
  return point && point.x >= inset && point.x <= world.camera.width - inset &&
    point.y >= inset && point.y <= world.camera.height - inset;
}

// Re-select destinations in the camera's current view. Prefer connected
// components inside the view so a long journey cannot detour around overscan.
export function createVisibleLoginPacket(world, tile, offset, elapsed, random = Math.random, key = '') {
  const visible = tile.scene.graph.points.filter(point => inViewport(world, projectLoginWorldPoint(world, tile.row, point, offset), 20));
  const allowed = new Set(visible.map(point => point.id));
  const remaining = new Set(allowed);
  const components = [];
  while (remaining.size) {
    const queue = [remaining.values().next().value];
    remaining.delete(queue[0]);
    for (let index = 0; index < queue.length; index++) {
      for (const edge of tile.scene.graph.adjacency[queue[index]]) {
        if (!remaining.has(edge.to)) continue;
        remaining.delete(edge.to); queue.push(edge.to);
      }
    }
    const tasks = tile.scene.nodes.filter(node => queue.includes(node.id));
    if (tasks.length >= 2) components.push(tasks);
  }
  let endpoints;
  let allowedIds = allowed;
  if (components.length) endpoints = components[Math.floor(random() * components.length)];
  else {
    endpoints = tile.scene.nodes.filter(node => allowed.has(node.id));
    // On a narrow view, visible junctions are valid network nodes as well.
    if (endpoints.length < 2) endpoints = visible;
    allowedIds = null;
  }
  if (endpoints.length < 2) return null;
  const packet = createLoginPacket({ ...tile.scene, packetNodes: endpoints }, random, { key, startedAt: elapsed, allowedIds });
  if (!packet) return null;
  return { ...packet, delay: 0, junctionEndpoints: endpoints.some(point => !tile.scene.nodes.some(node => node.id === point.id)) };
}

const packetArcCache = new WeakMap();
function curvePoint(curve, t) {
  const u = 1 - t;
  return { x: u ** 3 * curve.from.x + 3 * u * u * t * curve.control1.x + 3 * u * t * t * curve.control2.x + t ** 3 * curve.to.x,
    y: u ** 3 * curve.from.y + 3 * u * u * t * curve.control1.y + 3 * u * t * t * curve.control2.y + t ** 3 * curve.to.y };
}
function packetPointAtDistance(packet, distance) {
  if (distance < 0 || distance > packet.length) return null;
  let arcs = packetArcCache.get(packet);
  if (!arcs) {
    arcs = packet.curves.map(curve => {
      const samples = [0];
      let previous = curve.from;
      for (let index = 1; index <= 32; index++) {
        const point = curvePoint(curve, index / 32);
        samples.push(samples.at(-1) + Math.hypot(point.x - previous.x, point.y - previous.y));
        previous = point;
      }
      return { curve, samples, length: samples.at(-1) };
    });
    packetArcCache.set(packet, arcs);
  }
  for (const { curve, samples, length } of arcs) {
    if (distance > length) { distance -= length; continue; }
    const next = Math.max(1, samples.findIndex(sample => sample >= distance));
    const fraction = (distance - samples[next - 1]) / Math.max(.000001, samples[next] - samples[next - 1]);
    return curvePoint(curve, (next - 1 + fraction) / 32);
  }
  return packet.points.at(-1);
}

export function loginPacketVisible(world, tile, packet, offset, elapsed) {
  const age = elapsed - (packet.startedAt ?? 0) - packet.delay - LOGIN_NODE_CHARGE_TIME;
  // Charging and receiving endpoints are also visible parts of the journey.
  if (age < -LOGIN_NODE_CHARGE_TIME || age > packet.flowDuration + LOGIN_NODE_SETTLE_TIME) return false;
  if (age < 0) return inViewport(world, projectLoginWorldPoint(world, tile.row, packet.sourceNode, offset));
  if (age > packet.flowDuration) return inViewport(world, projectLoginWorldPoint(world, tile.row, packet.targetNode, offset));
  if (age >= (packet.length - packet.head) / packet.speed &&
      inViewport(world, projectLoginWorldPoint(world, tile.row, packet.targetNode, offset))) return true;
  const distance = age * packet.speed;
  return [distance + packet.head / 2, distance - packet.tail / 2].some(sample => {
    const point = packetPointAtDistance(packet, sample);
    return point && inViewport(world, projectLoginWorldPoint(world, tile.row, point, offset));
  });
}
export function loginPacketNodeTiming(packet) {
  return {
    sourceRelease: (packet.tail - packet.head) / packet.speed,
    targetArrival: (packet.length - packet.head) / packet.speed,
    targetReceive: (packet.tail + packet.head) / packet.speed,
  };
}
export function loginVisibleFlowTarget(world) {
  return world.camera.width < 600 ? 1 : world.camera.width * world.camera.height > 3000000 ? 3 : 2;
}
export function refreshLoginVisiblePackets(world, offset, elapsed, random = Math.random, makeKey = () => `visible:${Math.random()}`) {
  // Leave time for the next check and a replacement node's initial charge.
  const lookAhead = LOGIN_FLOW_CHECK_INTERVAL + LOGIN_NODE_CHARGE_TIME + .08;
  let stable = world.tiles.reduce((count, tile) => count + tile.scene.packets.filter(packet =>
    loginPacketVisible(world, tile, packet, offset, elapsed) &&
    loginPacketVisible(world, tile, packet, offset + LOGIN_CAMERA_SPEED * lookAhead, elapsed + lookAhead)).length, 0);
  const target = loginVisibleFlowTarget(world);
  if (stable >= target) return world;
  let changed = false;
  const tiles = [...world.tiles];
  for (const tile of shuffled(world.tiles, random)) {
    let packets = tile.scene.packets;
    for (let attempt = 0; stable < target && attempt < target * 4; attempt++) {
      const next = createVisibleLoginPacket(world, tile, offset, elapsed, random, makeKey());
      if (!next || !loginPacketVisible(world, tile, next, offset + LOGIN_CAMERA_SPEED * lookAhead, elapsed + lookAhead)) continue;
      const free = packets.findIndex(packet => !loginPacketVisible(world, tile, packet, offset, elapsed));
      if (free < 0 && packets.length >= target + 12) break;
      packets = free < 0 ? [...packets, next] : packets.map((packet, index) => index === free ? next : packet);
      stable++;
    }
    if (packets !== tile.scene.packets) {
      changed = true;
      tiles[tiles.indexOf(tile)] = { ...tile, scene: { ...tile.scene, packets } };
    }
    if (stable >= target) break;
  }
  return changed ? { ...world, tiles } : world;
}
