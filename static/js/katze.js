/* Katze, the app's cat. Inline SVG only (the CSP allows no external assets), eight avatar variants
   that match the server's ids (katze-1 … katze-8) and five moods used across the app:
   happy (home, replies), thinking (typing state), proud (milestones), sleepy (streak at risk),
   cheering (rings closed). Katze's lines are dry, short and never end in an exclamation mark. */
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

/* Each learner keeps one colour everywhere (race bars, head-to-head), whoever is looking. */
export function personColor(user, all) {
  const ids = (all || []).map((u) => u.id).sort((a, b) => a - b);
  return ids.indexOf(user.id) === 0 ? 'var(--accent)' : 'var(--cat-gender)';
}
export const variantName = (id) => (FUR[id] || FUR['katze-1']).name;

function eyes(mood, eye) {
  switch (mood) {
    case 'proud': return '<path d="M20 36 Q24 31 28 36" stroke="#15181f" stroke-width="2.2" fill="none" stroke-linecap="round"/><path d="M36 36 Q40 31 44 36" stroke="#15181f" stroke-width="2.2" fill="none" stroke-linecap="round"/><circle cx="19" cy="43" r="2.6" fill="#f48c8c" opacity=".6"/><circle cx="45" cy="43" r="2.6" fill="#f48c8c" opacity=".6"/>';
    case 'sleepy': return '<path d="M20 36 Q24 39 28 36" stroke="#15181f" stroke-width="2.2" fill="none" stroke-linecap="round"/><path d="M36 36 Q40 39 44 36" stroke="#15181f" stroke-width="2.2" fill="none" stroke-linecap="round"/>';
    case 'thinking': return `<ellipse cx="25" cy="33" rx="3.4" ry="4.2" fill="${eye}"/><ellipse cx="41" cy="33" rx="3.4" ry="4.2" fill="${eye}"/><path d="M20 27 L28 29" stroke="#15181f" stroke-width="2" stroke-linecap="round"/>`;
    case 'cheering': return `<ellipse cx="24" cy="34" rx="3.6" ry="4.6" fill="${eye}"/><ellipse cx="40" cy="34" rx="3.6" ry="4.6" fill="${eye}"/>`;
    default: return `<ellipse cx="24" cy="35" rx="3.4" ry="4.2" fill="${eye}"/><ellipse cx="40" cy="35" rx="3.4" ry="4.2" fill="${eye}"/><circle cx="25.2" cy="33.4" r="1.1" fill="#fff"/><circle cx="41.2" cy="33.4" r="1.1" fill="#fff"/>`;
  }
}

function mouth(mood) {
  if (mood === 'cheering') return '<ellipse cx="32" cy="49" rx="4" ry="3" fill="#15181f"/>';
  if (mood === 'sleepy') return '<path d="M28 48 Q32 50 36 48" stroke="#15181f" stroke-width="1.4" fill="none" stroke-linecap="round"/>';
  if (mood === 'thinking') return '<path d="M32 45 Q30 48 27.5 47" stroke="#15181f" stroke-width="1.4" fill="none" stroke-linecap="round"/>';
  if (mood === 'proud') return '<path d="M32 45 Q30 49 26.5 47.5 M32 45 Q34 49 37.5 47.5" stroke="#15181f" stroke-width="1.4" fill="none" stroke-linecap="round"/>';
  return '<path d="M32 45 Q30 48 27.5 47 M32 45 Q34 48 36.5 47" stroke="#15181f" stroke-width="1.4" fill="none" stroke-linecap="round"/>';
}

function extras(v, mood) {
  let s = '';
  if (v.calico) s += '<path d="M14 30 Q22 18 34 20 Q30 30 20 36 Z" fill="#f2b267"/><path d="M40 20 Q52 26 52 40 Q44 34 38 26 Z" fill="#2a2f3a"/>';
  if (v.stripes) s += '<path d="M26 17 L28 24 M32 15 L32 23 M38 17 L36 24" stroke="#7a5230" stroke-width="2" stroke-linecap="round"/>';
  if (v.mask) s += '<path d="M24 30 Q32 24 40 30 Q40 44 32 48 Q24 44 24 30 Z" fill="#5a4635" opacity=".5"/>';
  if (v.glasses) s += '<circle cx="24" cy="35" r="7" fill="none" stroke="#6b8cff" stroke-width="1.8"/><circle cx="40" cy="35" r="7" fill="none" stroke="#6b8cff" stroke-width="1.8"/><path d="M31 35h2" stroke="#6b8cff" stroke-width="1.8"/>';
  if (v.bow) s += '<path d="M44 12 L52 8 L50 16 Z M44 12 L38 10 L40 17 Z" fill="#f17fb0"/><circle cx="44" cy="12.5" r="2" fill="#ffd1e6"/>';
  if (v.scarf) s += '<path d="M14 52 Q32 60 50 52 L50 58 Q32 66 14 58 Z" fill="#e0725c"/>';
  if (v.headphones) s += '<path d="M10 36 Q10 14 32 14 Q54 14 54 36" stroke="#6b8cff" stroke-width="3" fill="none"/><rect x="6" y="32" width="8" height="12" rx="3" fill="#6b8cff"/><rect x="50" y="32" width="8" height="12" rx="3" fill="#6b8cff"/>';
  if (v.beret) s += '<ellipse cx="30" cy="16" rx="14" ry="5" fill="#e0725c"/><circle cx="30" cy="11" r="2" fill="#e0725c"/>';
  if (v.collar) s += '<path d="M14 54 Q32 62 50 54" stroke="#3ddc97" stroke-width="4" fill="none" stroke-linecap="round"/><circle cx="32" cy="59" r="3" fill="#ffb84d"/>';
  if (mood === 'cheering') s += '<path d="M6 20 l2 -5 l2 5 M54 16 l2 -5 l2 5" stroke="#ffb84d" stroke-width="1.6" fill="none" stroke-linecap="round"/>';
  if (mood === 'proud') s += '<path d="M50 4 l1.6 -4 l1.6 4 l-1.6 4z" fill="#ffb84d"/>';
  if (mood === 'sleepy') s += '<path d="M46 22 l2 -2 l2 2 M48 20 v6" stroke="#6b8cff" stroke-width="1.6" fill="none" stroke-linecap="round"/>';
  return s;
}

/* An <svg> element. `variant` is a server avatar id, `mood` one of the five, `size` in px. */
export function katze({ variant = 'katze-1', mood = 'happy', size = 48, label = null } = {}) {
  const v = FUR[variant] || FUR['katze-1'];
  const svg = `<svg viewBox="0 0 64 64" width="${size}" height="${size}" ${label ? `role="img" aria-label="${label}"` : 'aria-hidden="true"'}>
<path d="M13 27 L9 7 L27 19 Z" fill="${v.fur}"/><path d="M51 27 L55 7 L37 19 Z" fill="${v.fur}"/>
<path d="M16 25 L13 12 L25 20 Z" fill="${v.ear}"/><path d="M48 25 L51 12 L39 20 Z" fill="${v.ear}"/>
<circle cx="32" cy="37" r="22" fill="${v.fur}"/>
${v.calico ? extras({ calico: true }, '') : ''}${v.stripes ? extras({ stripes: true }, '') : ''}${v.mask ? extras({ mask: true }, '') : ''}
${eyes(mood, v.eye)}
<path d="M29.5 42 L34.5 42 L32 45 Z" fill="#e0725c"/>
${mouth(mood)}
<path d="M8 40 L22 42 M8 46 L22 44 M56 40 L42 42 M56 46 L42 44" stroke="#15181f" stroke-width="1.2" stroke-linecap="round" opacity=".55"/>
${extras({ glasses: v.glasses, bow: v.bow, scarf: v.scarf, headphones: v.headphones, beret: v.beret, collar: v.collar }, mood)}
</svg>`;
  const wrap = h('span', { class: `katze katze-${mood}`, html: svg });
  return wrap;
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
    case 'due': return `${ctx.n} cards are due. About ${Math.max(1, Math.round(ctx.n / 4))} minutes.`;
    case 'lesson': return 'The lesson first. Practice assumes someone taught you.';
    case 'empty': return 'Nothing due, nothing waiting. Talk to me anyway.';
    default: return '';
  }
}
