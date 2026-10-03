import assert from 'node:assert/strict';
import { glassDisplacementAt, createGlassDisplacementField, GLASS_DISPLACEMENT_SCALE, GLASS_MAP_PADDING } from '../src/glassOptics.js';

for (const [width, height] of [[1000, 505], [358, 802], [1920, 900]]) {
  const center = glassDisplacementAt(width / 2, height / 2, width, height, 20);
  assert.deepEqual(center, { x: 0, y: 0 }, 'The centre must stay clear and aligned');
  const left = glassDisplacementAt(9, height / 2, width, height, 20);
  const right = glassDisplacementAt(width - 9, height / 2, width, height, 20);
  assert.ok(left.x < -2 && right.x > 2, 'The bevel must refract the image while keeping its centre clear');
  let previousSampleY = 0;
  for (let y = 0; y < Math.min(height / 2, 64); y += .5) {
    const sampleY = y + glassDisplacementAt(width / 2, y, width, height, 20).y;
    assert.ok(sampleY >= previousSampleY - 1e-6, 'Edge sampling must not fold back and create doubled wires');
    previousSampleY = sampleY;
  }
  assert.ok(Math.abs(left.x + right.x) < 1e-9 && Math.abs(left.y) < 1e-9, 'Opposite edges must refract symmetrically');
  const corner = glassDisplacementAt(10, 10, width, height, 20);
  assert.ok(corner.x < 0 && corner.y < 0, 'The rounded corner needs both horizontal and vertical displacement');
  // A one-dimensional edge test missed the old discontinuity at the diagonal
  // between the two nearest edges. Check the whole rounded corner and seam.
  for (let x = 0; x <= 64; x += .5) {
    for (let y = 0; y <= 64; y += .5) {
      const sample = glassDisplacementAt(x, y, width, height, 20);
      const alongX = glassDisplacementAt(x + .01, y, width, height, 20);
      const alongY = glassDisplacementAt(x, y + .01, width, height, 20);
      const dx = { x: (alongX.x - sample.x) / .01, y: (alongX.y - sample.y) / .01 };
      const dy = { x: (alongY.x - sample.x) / .01, y: (alongY.y - sample.y) / .01 };
      assert.ok(Math.hypot(dx.x, dx.y) < 1 && Math.hypot(dy.x, dy.y) < 1,
        `No jump in the optical surface at ${x},${y}`);
      assert.ok((1 + dx.x) * (1 + dy.y) - dy.x * dx.y > .1,
        `The two-dimensional image must not fold or duplicate nodes at ${x},${y}`);
      const mirrored = glassDisplacementAt(width - x, height - y, width, height, 20);
      assert.ok(Math.abs(sample.x + mirrored.x) < 1e-8 && Math.abs(sample.y + mirrored.y) < 1e-8);
    }
  }
  const field = createGlassDisplacementField(width, height, 20, 1.5);
  assert.ok(field.width >= width * 1.5 && field.height >= height * 1.5, 'Use device-resolution maps instead of an enlarged thumbnail');
  assert.equal(field.padding, GLASS_MAP_PADDING, 'Neutral overscan keeps interpolation away from a transparent map boundary');
  assert.equal(field.data.length, field.width * field.height * 4);
  assert.equal(field.data[0], 128);
  assert.equal(field.data[1], 128);
  const centerIndex = (Math.floor(field.height / 2) * field.width + Math.floor(field.width / 2)) * 4;
  assert.equal(field.data[centerIndex], 128);
  assert.equal(field.data[centerIndex + 1], 128);
  for (let index = 0; index < field.data.length; index += 4) {
    assert.equal(field.data[index + 3], 255);
    assert.ok(Math.abs((field.data[index] - 128) / 255 * GLASS_DISPLACEMENT_SCALE) < 4);
    assert.ok(Math.abs((field.data[index + 1] - 128) / 255 * GLASS_DISPLACEMENT_SCALE) < 4);
  }
}
assert.deepEqual(glassDisplacementAt(0, 0, 1, 1, 0), { x: 0, y: 0 });
assert.equal(createGlassDisplacementField(100, 50, 20, 4).width, (100 + 2 * GLASS_MAP_PADDING) * 2, 'Cap supersampling at 2x');
console.log('Glass optics: continuous 2D refraction, no image folds, clear centre and device-resolution sampling passed.');
