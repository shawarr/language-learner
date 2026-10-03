/* write screen — filled in by its phase (docs/TASKS.md). */
import { h, clear } from './ui.js';

let root = null;

export function mount(el) {
  root = el;
  clear(root).append(h('div', { class: 'screen-body' }, h('p', { class: 'muted' }, 'Coming soon: write.')));
}
export function show() {}
export function hide() {}
