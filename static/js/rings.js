/* Apple-Fitness-style rings as inline SVG. Each ring animates from empty to its fraction on
   first paint (CSS transition on stroke-dashoffset, --slow). */
import { h } from './ui.js';

export function rings(list, size = 140) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', list.map((r) => `${r.key} ${Math.round((r.fraction || 0) * 100)} percent`).join(', '));
  const c = size / 2;
  const width = size * 0.085;
  const gap = width * 0.35;
  let r = c - width / 2 - 2;
  for (const ring of list) {
    const circ = 2 * Math.PI * r;
    const track = document.createElementNS(NS, 'circle');
    for (const [k, v] of Object.entries({ cx: c, cy: c, r, fill: 'none', stroke: ring.track, 'stroke-width': width })) track.setAttribute(k, v);
    const arc = document.createElementNS(NS, 'circle');
    for (const [k, v] of Object.entries({ cx: c, cy: c, r, fill: 'none', stroke: ring.color, 'stroke-width': width, 'stroke-linecap': 'round',
      'stroke-dasharray': circ, 'stroke-dashoffset': circ, transform: `rotate(-90 ${c} ${c})`, class: 'ring-arc' })) arc.setAttribute(k, v);
    svg.append(track, arc);
    const target = circ * (1 - Math.min(1, Math.max(0, ring.fraction || 0)));
    requestAnimationFrame(() => requestAnimationFrame(() => arc.setAttribute('stroke-dashoffset', target)));
    r -= width + gap;
  }
  return svg;
}

/* A single progress ring around content (level ring on the You screen). */
export function ringAround(fraction, size, color, track, content) {
  const wrap = h('div', { class: 'ring-wrap', style: { width: `${size}px`, height: `${size}px` } });
  const svg = rings([{ key: 'level', color, track, fraction }], size);
  svg.style.position = 'absolute';
  svg.style.inset = '0';
  wrap.append(svg, h('div', { class: 'ring-inner' }, content));
  return wrap;
}
