/* Katze, the app's cat. Inline SVG only (the CSP allows no external assets), eight avatar variants
   that match the server's ids (katze-1 … katze-8) and five moods used across the app:
   happy (home, replies), thinking (typing state), proud (milestones), sleepy (streak at risk),
   cheering (rings closed). She is alive: she breathes, blinks and glances about on her own,
   listens while the mic records, moves her mouth while the tutor speaks, and reacts to a right or
   wrong answer, a finished lesson and a tap (katzeState, katzeReact). Her sounds are in meow.js.
   Katze's lines are dry, short and never end in an exclamation mark. */
import { h } from './ui.js';

const FUR = {
  'katze-1': { fur: '#f2b267', ear: '#f7d7b5', eye: '#15181f', name: 'Ginger' },
  'katze-2': { fur: '#9aa3b4', ear: '#d6dbe4', eye: '#15181f', name: 'Grey', bow: true },
  'katze-3': { fur: '#2a2f3a', ear: '#3d4556', eye: '#e9ecf2', name: 'Black', glasses: true },
  'katze-4': { fur: '#e9ecf2', ear: '#f7d7b5', eye: '#15181f', name: 'White', scarf: true },
  'katze-5': { fur: '#e9ecf2', ear: '#f7d7b5', eye: '#15181f', name: 'Calico', calico: true },
  'katze-6': { fur: '#b98756', ear: '#d9b48a', eye: '#15181f', name: 'Tabby', stripes: true, headphones: true },
  'katze-7': { fur: '#eadfcf', ear: '#5a4635', eye: '#3b6cf6', name: 'Siamese', mask: true, beret: true },
  'katze-8': { fur: '#6f7f9c', ear: '#9aa9c4', eye: '#ffb84d', name: 'Blue', collar: true },
};
export const VARIANTS = Object.keys(FUR);

/* Each learner keeps one colour everywhere (race bars, head-to-head), whoever is looking. */
export function personColor(user, all) {
  const ids = (all || []).map((u) => u.id).sort((a, b) => a - b);
  return ids.indexOf(user.id) === 0 ? 'var(--accent)' : 'var(--cat-gender)';
}
export const variantName = (id) => (FUR[id] || FUR['katze-1']).name;

/* The art is grouped so parts can move: ears, head, eyes (and the pupils inside them), mouth,
   whiskers. A mood is a class on the wrapper (`k-think`, `k-sleep`, …); every moving part is CSS. */
function art(v, mood) {
  const line = v.fur === '#2a2f3a' ? '#e9ecf2' : INK;
  return `<g class="k-all p"><g class="k-body p"><g class="k-head p">
<g class="k-ear-l p"><path d="M13 27 L9 7 L27 19 Z" fill="${v.fur}"/><path d="M16 25 L13 12 L25 20 Z" fill="${v.ear}"/></g>
<g class="k-ear-r p"><path d="M51 27 L55 7 L37 19 Z" fill="${v.fur}"/><path d="M48 25 L51 12 L39 20 Z" fill="${v.ear}"/></g>
${v.headphones ? '<path d="M10 36 Q10 14 32 14 Q54 14 54 36" stroke="#6b8cff" stroke-width="3" fill="none"/>' : ''}
<circle cx="32" cy="37" r="22" fill="${v.fur}"/>
${v.calico ? '<path d="M14 30 Q22 18 34 20 Q30 30 20 36 Z" fill="#f2b267"/><path d="M40 20 Q52 26 52 40 Q44 34 38 26 Z" fill="#2a2f3a"/>' : ''}
${v.stripes ? '<path d="M26 17 L28 24 M32 15 L32 23 M38 17 L36 24" stroke="#7a5230" stroke-width="2" stroke-linecap="round"/>' : ''}
${v.mask ? '<path d="M24 30 Q32 24 40 30 Q40 44 32 48 Q24 44 24 30 Z" fill="#5a4635" opacity=".5"/>' : ''}
<g class="k-blush"><circle cx="19" cy="43" r="2.8" fill="#f48c8c"/><circle cx="45" cy="43" r="2.8" fill="#f48c8c"/></g>
<g class="k-eyes p"><g class="k-pupils p"><ellipse cx="24" cy="35" rx="3.4" ry="4.2" fill="${v.eye}"/><ellipse cx="40" cy="35" rx="3.4" ry="4.2" fill="${v.eye}"/><circle cx="25.2" cy="33.4" r="1.1" fill="#fff"/><circle cx="41.2" cy="33.4" r="1.1" fill="#fff"/></g></g>
<path class="k-eyes-happy" d="M20 36 Q24 31 28 36 M36 36 Q40 31 44 36" stroke="${line}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
<path class="k-eyes-shut" d="M20 36 Q24 39 28 36 M36 36 Q40 39 44 36" stroke="${line}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
<path class="k-brow" d="M36 27.5 L44 25.5" stroke="${line}" stroke-width="2" stroke-linecap="round"/>
<path d="M29.5 42 L34.5 42 L32 45 Z" fill="#e0725c"/>
<path class="k-mouth p" d="M32 45 Q30 48 27.5 47 M32 45 Q34 48 36.5 47" stroke="${line}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
<ellipse class="k-mouth-open p" cx="32" cy="48.6" rx="3.2" ry="2.6" fill="${INK}"/>
<g class="k-whisk-l p"><path d="M8 40 L22 42 M8 46 L22 44" stroke="${line}" stroke-width="1.2" stroke-linecap="round" opacity=".55"/></g>
<g class="k-whisk-r p"><path d="M56 40 L42 42 M56 46 L42 44" stroke="${line}" stroke-width="1.2" stroke-linecap="round" opacity=".55"/></g>
${v.glasses ? '<circle cx="24" cy="35" r="7" fill="none" stroke="#6b8cff" stroke-width="1.8"/><circle cx="40" cy="35" r="7" fill="none" stroke="#6b8cff" stroke-width="1.8"/><path d="M31 35h2" stroke="#6b8cff" stroke-width="1.8"/>' : ''}
${v.bow ? '<path d="M44 12 L52 8 L50 16 Z M44 12 L38 10 L40 17 Z" fill="#f17fb0"/><circle cx="44" cy="12.5" r="2" fill="#ffd1e6"/>' : ''}
${v.headphones ? '<rect x="6" y="32" width="8" height="12" rx="3" fill="#6b8cff"/><rect x="50" y="32" width="8" height="12" rx="3" fill="#6b8cff"/>' : ''}
${v.beret ? '<ellipse cx="30" cy="16" rx="14" ry="5" fill="#e0725c"/><circle cx="30" cy="11" r="2" fill="#e0725c"/>' : ''}
</g>
${v.scarf ? '<path d="M14 52 Q32 60 50 52 L50 58 Q32 66 14 58 Z" fill="#e0725c"/>' : ''}
${v.collar ? '<path d="M14 54 Q32 62 50 54" stroke="#3ddc97" stroke-width="4" fill="none" stroke-linecap="round"/><circle cx="32" cy="59" r="3" fill="#ffb84d"/>' : ''}
</g></g>
${mood === 'cheering' ? '<path d="M6 20 l2 -5 l2 5 M54 16 l2 -5 l2 5" stroke="#ffb84d" stroke-width="1.6" fill="none" stroke-linecap="round"/>' : ''}
${mood === 'proud' ? '<path d="M50 4 l1.6 -4 l1.6 4 l-1.6 4z" fill="#ffb84d"/>' : ''}
${mood === 'sleepy' ? '<path d="M46 22 l2 -2 l2 2 M48 20 v6" stroke="#6b8cff" stroke-width="1.6" fill="none" stroke-linecap="round"/>' : ''}`;
}

const INK = '#15181f';
// The app's five moods, as the state classes the CSS animates.
const MOOD_CLASS = { happy: '', thinking: 'k-think', proud: 'k-proud', sleepy: 'k-sleep', cheering: 'k-proud k-hop' };
const reduced = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

/* An element with an <svg> inside. `variant` is a server avatar id, `mood` one of the five, `size`
   in px. Katze is alive by default: breathing and blinking, glancing about, petting on a tap. */
export function katze({ variant = 'katze-1', mood = 'happy', size = 48, label = null, alive = true } = {}) {
  const v = FUR[variant] || FUR['katze-1'];
  const svg = `<svg viewBox="0 0 64 64" width="${size}" height="${size}" ${label ? `role="img" aria-label="${label}"` : 'aria-hidden="true"'}>${art(v, mood)}</svg>`;
  const wrap = h('span', { class: `katze katze-${mood} ${MOOD_CLASS[mood] || ''} ${alive ? 'alive' : ''}`, html: svg });
  wrap.dataset.mood = MOOD_CLASS[mood] || '';
  if (alive) startLife();
  return wrap;
}

/* ---- life ------------------------------------------------------------------------------------
   One clock for every Katze on screen: each gets its own next blink, glance and ear flick, so two
   cats side by side never move in step. Nothing runs while the page is hidden or motion is reduced. */
let clock = null;
const next = new WeakMap();
function startLife() {
  if (clock || reduced()) return;
  clock = setInterval(() => {
    if (document.hidden) return;
    const now = Date.now();
    for (const el of document.querySelectorAll('.katze.alive')) {
      const at = next.get(el);
      if (!at) { next.set(el, now + 800 + Math.random() * 2500); continue; }
      if (now < at) continue;
      next.set(el, now + 2600 + Math.random() * 3600);
      if (el.matches('.k-sleep, .k-proud, .k-right, .k-pet, .k-party')) continue;
      blink(el);
      const r = Math.random();
      if (r < .22) setTimeout(() => blink(el), 260);
      if (r > .55 && !el.matches('.k-think, .k-listen, .k-wrong')) glance(el);
      if (r > .72) flick(el);
    }
  }, 400);
}
function blink(el) { el.classList.add('k-blink'); setTimeout(() => el.classList.remove('k-blink'), 120); }
function glance(el) {
  const p = el.querySelector('.k-pupils');
  if (!p) return;
  const [x, y] = [[-2.2, 0], [2.2, 0], [1.5, -1.5], [-1.5, 1]][Math.floor(Math.random() * 4)];
  p.style.transform = `translate(${x}px, ${y}px)`;
  setTimeout(() => { p.style.transform = ''; }, 1000 + Math.random() * 900);
}
function flick(el) {
  const side = Math.random() < .5 ? 'k-flick-l' : 'k-flick-r';
  el.classList.add(side);
  setTimeout(() => el.classList.remove(side), 480);
}

/* A lasting state: 'listen' (the mic is recording), 'talk' (the tutor's voice plays), 'think', or
   null to go back to the mood Katze was drawn with. */
export function katzeState(el, state) {
  if (!el) return;
  el.classList.remove('k-listen', 'k-talk', 'k-think');
  if (state) el.classList.add(`k-${state}`);
  else if (el.dataset.mood) el.classList.add(...el.dataset.mood.split(' ').filter((c) => c === 'k-think'));
}

/* A one-off reaction that settles by itself: 'right', 'wrong', 'pet', 'party'. */
const SETTLE = { right: 900, wrong: 2600, pet: 2000, party: 1600 };
export function katzeReact(el, kind) {
  if (!el || reduced()) return;
  el.classList.remove('k-right', 'k-wrong', 'k-pet', 'k-party');
  void el.offsetWidth;   // restart the animation when the same reaction comes twice
  el.classList.add(`k-${kind}`);
  fx(el, kind);
  clearTimeout(el._settle);
  el._settle = setTimeout(() => el.classList.remove(`k-${kind}`), SETTLE[kind] || 1000);
}

/* Sparks, hearts and confetti, drawn around the cat and thrown away after. */
function fx(el, kind) {
  const size = el.getBoundingClientRect().width || 48;
  const layer = h('span', { class: 'k-fx', 'aria-hidden': 'true' });
  el.append(layer);
  setTimeout(() => layer.remove(), 2000);
  const add = (cls, vars, text = '') => {
    const i = h('i', { class: cls }, text);
    for (const [k, v] of Object.entries(vars)) i.style.setProperty(k, v);
    layer.append(i);
  };
  const k = Math.max(.5, size / 120);
  if (kind === 'right') for (let n = 0; n < 7; n++) { const a = n / 7 * Math.PI * 2; add('k-spark', { '--x': `${Math.cos(a) * 46 * k}px`, '--y': `${Math.sin(a) * 40 * k}px` }); }
  if (kind === 'pet') for (let n = 0; n < 3; n++) setTimeout(() => add('k-heart', { '--x': `${(Math.random() - .5) * 50 * k}px` }, '♥'), n * 260);
  if (kind === 'party') {
    const cols = ['var(--accent)', '#ffb84d', '#f17fb0', '#6b8cff', '#3ddc97'];
    for (let n = 0; n < 22; n++) add('k-conf', { background: cols[n % 5], '--x': `${(Math.random() - .5) * 200 * k}px`, '--y': `${(Math.random() * -1.1 - .1) * 110 * k}px`, '--r': `${Math.random() * 720 - 360}deg` });
  }
}

/* Tap a Katze anywhere and she enjoys it, unless she is a button, where the tap belongs to the
   button. The purr comes from meow.js; this module only knows that a pet happened. */
let petListener = false;
export function onPet(fn) {
  if (petListener) return;
  petListener = true;
  document.addEventListener('click', (e) => {
    const el = e.target.closest && e.target.closest('.katze.alive');
    if (!el || el.closest('button, a, [role="button"]')) return;
    katzeReact(el, 'pet');
    fn && fn(el);
  });
}

/* Katze's one-liners. Pick by situation; the caller passes the numbers. */
export function says(kind, ctx = {}) {
  const other = ctx.otherName || 'the other one';
  switch (kind) {
    case 'rings_all': return 'Three rings. That is a good evening.';
    case 'rings_two': return 'Two rings. One more and the day is round.';
    case 'behind': return `${other} is ${ctx.gap} XP ahead. One conversation closes most of it.`;
    case 'ahead': return `You lead by ${ctx.gap} XP. ${other} usually catches up after dinner.`;
    case 'tied': return `Level with ${other}. Whoever reviews tonight pulls ahead.`;
    case 'streak_risk': return 'Your streak sleeps at midnight. One review keeps it awake.';
    case 'due': return ctx.n === 1 ? 'One card is due. About a minute.' : `${ctx.n} cards are due. About ${Math.max(1, Math.round(ctx.n / 4))} minutes.`;
    case 'lesson': return 'The lesson first. Practice assumes someone taught you.';
    case 'empty': return 'Nothing due, nothing waiting. Talk to me anyway.';
    default: return '';
  }
}
