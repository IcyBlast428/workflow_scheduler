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

function pathFromPoints(points) {
  return points.map((point, index) => `${index ? 'L' : 'M'}${point.x} ${point.y}`).join('');
}

function pathLength(points) {
  return points.slice(1).reduce((length, point, index) => length + Math.hypot(point.x - points[index].x, point.y - points[index].y), 0);
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
export function createLoginPacket(scene, random = Math.random, { key = '', stagger = false } = {}) {
  const source = scene.nodes[Math.floor(random() * scene.nodes.length)].id;
  const parents = Array(scene.graph.points.length).fill(null);
  const distances = Array(scene.graph.points.length).fill(-1);
  const queue = [source];
  distances[source] = 0;
  for (let index = 0; index < queue.length; index++) {
    const from = queue[index];
    for (const edge of shuffled(scene.graph.adjacency[from], random)) {
      if (distances[edge.to] !== -1) continue;
      parents[edge.to] = { from, edge };
      distances[edge.to] = distances[from] + 1;
      queue.push(edge.to);
    }
  }
  let targets = scene.nodes.filter(node => node.id !== source && distances[node.id] > 0);
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
  const nodeIds = [source];
  for (const step of steps) {
    points.push(...step.points.slice(1));
    nodeIds.push(step.to);
  }
  const length = pathLength(points);
  const head = Math.min(10, length * .15);
  const tail = Math.min(64, length * .3);
  const travel = length + tail;
  const period = travel + tail + head;
  const duration = Math.max(3.5, travel / (75 + random() * 40));
  return {
    key, path: pathFromPoints(points), points, nodeIds, source, target, hops: steps.length,
    length, travel, period, head, tail, duration,
    delay: stagger ? -random() * duration : random() * .8,
  };
}

export function createLoginBackdropScene(width, height, seed) {
  width = Math.max(1, Math.round(width));
  height = Math.max(1, Math.round(height));
  const random = randomFromSeed(seed);
  const round = value => Math.round(value);
  const between = (start, end) => start + random() * (end - start);
  const columns = Math.min(18, Math.max(2, Math.ceil(width / 330)));
  const rows = Math.min(12, Math.max(2, Math.ceil(height / 270)));
  const cellWidth = width / columns;
  const cellHeight = height / rows;
  const timelineY = round(height * between(.08, .17));
  const timelineClearance = Math.min(60, Math.max(32, round(height * .06)), height * .25);
  const timelineBand = { top: timelineY - timelineClearance, bottom: timelineY + timelineClearance };
  const nodeMargin = Math.min(16, height * .1);
  const clearTimeline = y => {
    if (y < timelineBand.top - nodeMargin || y > timelineBand.bottom + nodeMargin) return y;
    const above = timelineBand.top - nodeMargin;
    const below = timelineBand.bottom + nodeMargin;
    return round(above >= nodeMargin && y - above < below - y ? above : below);
  };
  const points = [];
  const nodes = [];
  const junctions = [];
  const routes = [];

  for (let row = 0; row < rows; row++) {
    const band = [];
    for (let column = 0; column < columns; column++) {
      const point = {
        id: row * columns + column,
        x: round((column + between(.25, .75)) * cellWidth),
        y: clearTimeline(round((row + between(.25, .75)) * cellHeight)),
      };
      band.push(point);
      if (random() < .52 || (row + column) % 5 === 0 || (row === rows - 1 && column === columns - 1)) {
        nodes.push({ ...point, gold: random() < .2, radius: round(between(10, 14)) });
      } else {
        junctions.push(point);
      }
    }
    points.push(band);
  }

  const graph = { points: points.flat(), adjacency: Array.from({ length: rows * columns }, () => []) };
  const minimumBend = Math.min(38, cellWidth * .15, cellHeight * .15);
  const connect = (from, to, edge = false) => {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const ax = Math.abs(dx);
    const ay = Math.abs(dy);
    const vertices = [from];
    // A close alignment gets a direct line, never a tiny corrective stair.
    if (Math.min(ax, ay) >= minimumBend && Math.abs(ax - ay) >= minimumBend) {
      let corner;
      if (random() < .65) {
        const diagonalFirst = random() < .5;
        if (ax >= ay) {
          corner = diagonalFirst ? { x: from.x + Math.sign(dx) * ay, y: to.y } : { x: to.x - Math.sign(dx) * ay, y: from.y };
        } else {
          corner = diagonalFirst ? { x: to.x, y: from.y + Math.sign(dy) * ax } : { x: from.x, y: to.y - Math.sign(dy) * ax };
        }
      } else {
        corner = random() < .5 ? { x: to.x, y: from.y } : { x: from.x, y: to.y };
      }
      vertices.push(corner);
    }
    vertices.push(to);
    const crowdsTimeline = vertices.slice(1).some((point, index) => {
      const previous = vertices[index];
      return Math.abs(point.y - previous.y) < Math.abs(point.x - previous.x) * .7 &&
        Math.max(point.y, previous.y) >= timelineBand.top && Math.min(point.y, previous.y) <= timelineBand.bottom;
    });
    if (crowdsTimeline) {
      // Keep horizontal legs outside the lane; only cross it vertically.
      const corner = random() < .5 ? { x: to.x, y: from.y } : { x: from.x, y: to.y };
      vertices.splice(0, vertices.length, from, corner, to);
    }
    routes.push({ path: pathFromPoints(vertices), points: vertices, edge });
    if (!edge) {
      graph.adjacency[from.id].push({ to: to.id, points: vertices });
      graph.adjacency[to.id].push({ to: from.id, points: [...vertices].reverse() });
    }
  };

  // Connect neighbouring cells so the circuits extend over the whole surface.
  for (let row = 0; row < rows; row++) {
    for (let column = 0; column < columns; column++) {
      const point = points[row][column];
      if (column && row) {
        const horizontal = random() < .5;
        connect(horizontal ? points[row][column - 1] : points[row - 1][column], point);
        if (random() < .35) connect(horizontal ? points[row - 1][column] : points[row][column - 1], point);
      } else if (column) {
        connect(points[row][column - 1], point);
      } else if (row) {
        connect(points[row - 1][column], point);
      }
    }
  }

  // Ports run to the page edges, including the corners of very wide screens.
  for (let column = 0; column < columns; column += 2) {
    const top = points[0][column];
    const bottom = points[rows - 1][column];
    connect({ x: top.x, y: -12 }, top, true);
    connect(bottom, { x: bottom.x, y: height + 12 }, true);
  }
  for (let row = 0; row < rows; row += 2) {
    connect({ x: -12, y: points[row][0].y }, points[row][0], true);
    connect(points[row][columns - 1], { x: width + 12, y: points[row][columns - 1].y }, true);
  }

  const sideSpace = Math.max(120, (width - Math.min(1000, width - 48)) / 2);
  const radius = round(Math.min(172, sideSpace * .65, height * .23));
  const rightSide = random() < .5;
  const clockX = between(sideSpace * .3, sideSpace * .7);
  const clockY = (clockRadius, low, high) => round(Math.min(height - clockRadius - 12,
    Math.max(timelineBand.bottom + clockRadius + 16, between(low, high) * height)));
  const clocks = [{
    x: round(rightSide ? width - clockX : clockX), y: clockY(radius, .26, .74),
    scale: radius / 176, angle: round(between(0, 360)),
  }];
  if (width > 2200 || (width > 1100 && height > 1300)) {
    const otherX = between(sideSpace * .3, sideSpace * .7);
    clocks.push({ x: round(rightSide ? otherX : width - otherX), y: clockY(radius * .55, .2, .8), scale: radius * .55 / 176, angle: round(between(0, 360)) });
  }

  const times = ['00:00', '06:00', '12:00', '18:00'].map((label, index) => ({
    label, x: round(width * (.1 + index * .26)),
  }));
  const scene = { width, height, nodes, junctions, routes, graph, clocks, timelineY, timelineBand, times, preferredHops: Math.min(7, Math.max(3, Math.floor((rows + columns) / 2))) };
  const packetCount = width < 600 ? 3 : width * height > 3000000 ? 12 : 8;
  scene.packets = Array.from({ length: packetCount }, (_, index) => createLoginPacket(scene, random, { key: `${width}:${height}:initial:${index}`, stagger: true }));
  return scene;
}
