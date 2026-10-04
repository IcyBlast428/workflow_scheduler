import { createGlassDisplacementField, GLASS_DISPLACEMENT_SCALE, GLASS_MAP_PADDING } from './glassOptics';

let sequence = 0;
const panes = new WeakMap();
const SVG_NS = 'http://www.w3.org/2000/svg';
function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

// Floating surfaces sample the actual page behind them. Only their bevel is
// refracted; no copy of the application and no filter on foreground text.
export const glassSurface = {
  mounted(element) {
    const definitions = svgElement('svg', { width: 0, height: 0, 'aria-hidden': 'true' });
    definitions.style.cssText = 'position:fixed;pointer-events:none;width:0;height:0';
    const id = `surface-lens-${sequence++}`;
    const filter = svgElement('filter', { id, filterUnits: 'userSpaceOnUse', primitiveUnits: 'userSpaceOnUse', 'color-interpolation-filters': 'sRGB' });
    const map = svgElement('feImage', { preserveAspectRatio: 'none', result: 'lens-map' });
    const transfer = svgElement('feComponentTransfer', { in: 'lens-map', result: 'unbiased-map' });
    for (const channel of ['R', 'G']) transfer.append(svgElement(`feFunc${channel}`, { type: 'linear', slope: 1, intercept: -.5 / 255 }));
    filter.append(map, transfer,
      svgElement('feGaussianBlur', { in: 'unbiased-map', stdDeviation: .65, result: 'smooth-map' }),
      svgElement('feDisplacementMap', { in: 'SourceGraphic', in2: 'smooth-map', scale: GLASS_DISPLACEMENT_SCALE, xChannelSelector: 'R', yChannelSelector: 'G' }));
    const defs = svgElement('defs'); defs.append(filter); definitions.append(defs);
    document.body.append(definitions);
    let frame = 0, dimensions = '';
    const measure = () => {
      frame = 0;
      const width = element.clientWidth, height = element.clientHeight;
      if (!width || !height) return;
      const radius = parseFloat(getComputedStyle(element).borderTopLeftRadius) || 20;
      const ratio = window.devicePixelRatio || 1;
      const key = `${width}:${height}:${radius}:${ratio}`;
      if (key === dimensions) return;
      const field = createGlassDisplacementField(width, height, radius, ratio);
      const canvas = document.createElement('canvas');
      canvas.width = field.width; canvas.height = field.height;
      const context = canvas.getContext('2d');
      if (!context) return;
      context.putImageData(new ImageData(field.data, field.width, field.height), 0, 0);
      const bounds = { x: -GLASS_MAP_PADDING, y: -GLASS_MAP_PADDING, width: width + GLASS_MAP_PADDING * 2, height: height + GLASS_MAP_PADDING * 2 };
      for (const [name, value] of Object.entries(bounds)) { filter.setAttribute(name, value); map.setAttribute(name, value); }
      map.setAttribute('href', canvas.toDataURL('image/png'));
      element.style.setProperty('--surface-lens', `url("#${id}")`);
      dimensions = key;
    };
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame); frame = requestAnimationFrame(measure);
    });
    observer.observe(element);
    measure();
    panes.set(element, () => {
      observer.disconnect(); cancelAnimationFrame(frame); definitions.remove();
      element.style.removeProperty('--surface-lens');
    });
  },
  beforeUnmount(element) { panes.get(element)?.(); panes.delete(element); },
};
