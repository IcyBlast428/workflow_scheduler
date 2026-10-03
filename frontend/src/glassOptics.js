export const GLASS_DISPLACEMENT_SCALE = 16;
export const GLASS_MAP_PADDING = 12;

// One flat pane with a polished, rounded bevel. The bevel ends before the
// rounded rectangle's medial axis, where its nearest-edge normal is ambiguous.
// A quintic thickness profile has zero slope at both ends, so neither the edge
// nor the transition to the clear centre introduces a jump in the image.
export function glassDisplacementAt(x, y, width, height, radius) {
  const cx = width / 2;
  const cy = height / 2;
  radius = Math.max(0, Math.min(radius, cx, cy));
  if (!radius) return { x: 0, y: 0 };
  const qx = Math.abs(x - cx) - (cx - radius);
  const qy = Math.abs(y - cy) - (cy - radius);
  const ox = Math.max(qx, 0);
  const oy = Math.max(qy, 0);
  const outside = Math.hypot(ox, oy);
  const depth = -(outside + Math.min(Math.max(qx, qy), 0) - radius);
  const bevel = Math.min(18, radius * .9);
  if (depth <= 0 || depth >= bevel) return { x: 0, y: 0 };
  let nx = 0;
  let ny = 0;
  if (outside > 0) {
    nx = ox / outside * Math.sign(x - cx);
    ny = oy / outside * Math.sign(y - cy);
  }
  else if (qx > qy) nx = Math.sign(x - cx);
  else ny = Math.sign(y - cy);
  const t = depth / bevel;
  const thickness = bevel * (4 / 18);
  const surfaceHeight = thickness * t ** 3 * (10 - 15 * t + 6 * t * t);
  const slope = thickness / bevel * 30 * t * t * (1 - t) ** 2;
  // Trace a normal viewing ray through the curved front and a flat rear face
  // (air -> glass, index 1.5 -> air). Distances are expressed in CSS pixels.
  const incident = Math.atan(slope);
  const inGlass = incident - Math.asin(Math.sin(incident) / 1.5);
  const outgoing = Math.asin(Math.min(1, 1.5 * Math.sin(inGlass)));
  const shift = surfaceHeight * Math.tan(inGlass) + bevel * .75 * Math.tan(outgoing);
  return { x: nx * shift, y: ny * shift };
}

export function createGlassDisplacementField(width, height, radius, pixelRatio = 1) {
  const padding = GLASS_MAP_PADDING;
  const cssWidth = width + padding * 2;
  const cssHeight = height + padding * 2;
  // Never shrink below CSS resolution. Cap DPR, not pane dimensions: the old
  // 640px thumbnail stretched a staircase-shaped displacement over the card.
  const ratio = Math.max(1, Math.min(2, Number(pixelRatio) || 1));
  const mapWidth = Math.ceil(cssWidth * ratio);
  const mapHeight = Math.ceil(cssHeight * ratio);
  const data = new Uint8ClampedArray(mapWidth * mapHeight * 4);
  for (let row = 0; row < mapHeight; row++) {
    for (let column = 0; column < mapWidth; column++) {
      const offset = (row * mapWidth + column) * 4;
      const shift = glassDisplacementAt((column + .5) / mapWidth * cssWidth - padding,
        (row + .5) / mapHeight * cssHeight - padding, width, height, radius);
      // 128 is exact zero after the filter's half-byte bias correction.
      data[offset] = 128 + shift.x / GLASS_DISPLACEMENT_SCALE * 255;
      data[offset + 1] = 128 + shift.y / GLASS_DISPLACEMENT_SCALE * 255;
      data[offset + 2] = 128;
      data[offset + 3] = 255;
    }
  }
  return { width: mapWidth, height: mapHeight, padding, data };
}
