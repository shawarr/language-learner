/* One outline icon set for the learning screens, drawn like the tab bar: 24 px grid, 1.8 stroke,
   round caps. Inline SVG because the CSP allows nothing external. Decorative by default; a button
   that is only an icon carries its own aria-label. */
import { h } from './ui.js';

const PATHS = {
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  chevronRight: '<path d="M9 6l6 6-6 6"/>',
  chevronDown: '<path d="M6 9l6 6 6-6"/>',
  speaker: '<path d="M4 9.5v5h3.5L12 18V6L7.5 9.5z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  slow: '<path d="M4 15a8 8 0 0 1 16 0"/><path d="M12 15l3.5-4"/><path d="M4 19h16"/>',
  play: '<path d="M8 5.5v13l10-6.5z"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2.5"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
  trophy: '<path d="M8 21h8M12 17v4M6.5 4h11v4.5a5.5 5.5 0 0 1-11 0z"/><path d="M6.5 6H3.5v1.5a3 3 0 0 0 3 3M17.5 6h3v1.5a3 3 0 0 1-3 3"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
  keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M7.5 14h9"/>',
  send: '<path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M3 3l18 18"/><path d="M10.6 5.6A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.6 3.4M6.6 6.6C4 8.3 2.5 12 2.5 12S6 18.5 12 18.5a9.3 9.3 0 0 0 4.4-1.1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
  book: '<path d="M4 5h6a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H4z"/><path d="M20 5h-6a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h7z"/>',
  pen: '<path d="M4 17.3V20h2.7L17.8 8.9l-2.7-2.7z"/><path d="M14.4 7l2.7 2.7"/>',
  cards: '<rect x="3" y="7" width="13" height="13" rx="2"/><path d="M8 4h11a2 2 0 0 1 2 2v11"/>',
  bolt: '<path d="M13 2 4.5 13.5h6L10 22l8.5-11.5h-6z"/>',
  flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.5M4 5v4h4M4 13a8 8 0 0 0 14.6 4.5M20 19v-4h-4"/>',
  sparkle: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
  chat: '<path d="M4 5.5h16v10H9l-5 4z"/>',
};

/* <span class="ico"> holding the outline icon. `size` in px; colour follows currentColor. */
export function icon(name, size = 20, { label = null } = {}) {
  const a11y = label ? `role="img" aria-label="${label}"` : 'aria-hidden="true"';
  return h('span', { class: 'ico', style: { width: `${size}px`, height: `${size}px` },
    html: `<svg viewBox="0 0 24 24" ${a11y} fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${PATHS[name] || ''}</svg>` });
}
