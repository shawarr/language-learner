/* placement screen — filled in by phase C3 (docs/TASKS.md). */
import { h, clear } from './ui.js';

let root = null;

export function mount(el) {
  root = el;
  clear(root).append(h('div', { class: 'screen-body' }, h('p', { class: 'muted' }, 'Coming soon: placement.')));
}
/* Returns true when the placement flow should take over the screen (first launch). */
export async function gate() { return false; }
export function show() {}
export function hide() {}
