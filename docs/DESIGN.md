# Design spec — the frontend has to feel finished

Ahmad will use this every day, on his phone, usually tired after work. The difference between an app
he opens daily and one he abandons in a week is almost entirely in this document. "Functional" is not
the bar. It should feel like a well-made native app, not like a form with a microphone bolted on.

Build it with vanilla JS and CSS. There is no excuse for a framework here, and no excuse for a rough
edge either. Everything below is specific on purpose — if a number is given, use it.

---

## 1. The feeling to aim for

Calm, confident, quiet. A tutor's study, not a game show. No confetti, no streak-shaming, no mascot,
no exclamation marks in the UI copy. The German content is the loudest thing on screen; the chrome
recedes. When something is loading, the app looks like it's thinking, not like it's broken.

Three things must feel instant even when the network isn't: the tab switch, the mic press, and
revealing a flashcard. Everything else may take time, but must *say* it is taking time within 100 ms.

## 2. Tokens

Define these once on `:root` and never hardcode a value in a component. Dark is the default; light is
the `prefers-color-scheme: light` override.

```css
:root {
  /* dark (default) */
  --bg:        #0e1014;   /* page */
  --surface:   #171a21;   /* cards, bubbles */
  --surface-2: #1f232c;   /* raised: sheets, input */
  --line:      #2a2f3a;   /* hairlines */
  --text:      #e9ecf2;
  --text-dim:  #98a1b2;   /* secondary, timestamps */
  --accent:    #6b8cff;   /* interactive, tutor identity */
  --accent-dim:#2a3558;
  --good:      #3ddc97;   /* correct, passed */
  --warn:      #ffb84d;   /* corrections — NOT red */
  --bad:       #ff6b6b;   /* failures, destructive only */

  --r-sm: 8px; --r-md: 14px; --r-lg: 20px; --r-full: 999px;
  --s-1: 4px; --s-2: 8px; --s-3: 12px; --s-4: 16px; --s-5: 24px; --s-6: 32px;
  --fast: 120ms; --base: 200ms; --slow: 320ms;
  --ease: cubic-bezier(.2,.8,.2,1);          /* decelerate: entrances, expansions */
  --ease-in-out: cubic-bezier(.4,0,.2,1);
}
```

**Corrections are amber, never red.** Red says "you failed". Amber says "look here". He will see
corrections on most turns for months; they must not feel like punishment.

Type scale (system font stack — no webfont, the CSP blocks external ones and a download is a
render delay): 28/22/17/15/13 px, weights 400/500/600 only. German body text at **17 px minimum** —
he is reading a foreign language, often with unfamiliar words. Line height 1.5 for German text,
1.35 for UI labels. Never justify, never letter-space body text.

## 3. Layout and the hand

- Single column, max 560 px, centred, 16 px side gutters.
- Bottom tab bar fixed, 5 tabs, each ≥ 56 px tall plus
  `padding-bottom: env(safe-area-inset-bottom)`. Active tab: filled icon + accent label; inactive:
  outline icon + `--text-dim`. Label always visible — icon-only navigation is a guessing game.
- Everything interactive is **at least 44×44 px**, and the primary action of each screen sits in the
  bottom third where a thumb reaches.
- `overscroll-behavior: contain` on scrollers; `touch-action: manipulation` globally to kill the
  300 ms tap delay and double-tap zoom.
- Handle the keyboard with `visualViewport`: when it opens, the composer stays glued above it and the
  last message stays visible. This is the single most common way a chat UI feels broken on iOS.
- `100vh` is a lie on mobile Safari. Use `100dvh`.
- No horizontal scroll at 320 px. Test at 320, 390 and 430 px wide.

## 4. The Talk screen — this is the app

The centrepiece. Spend the most time here.

**Message list.** Tutor turns left-aligned on `--surface` with a subtle accent left-border; Ahmad's
turns right-aligned on `--accent-dim`. Radius `--r-lg` with the corner nearest the speaker at
`--r-sm` — the detail that makes bubbles read as speech. Max width 85 %. Messages enter with a 12 px
rise and fade over `--base`; the list scrolls to the new message with `behavior: smooth`, and
**only** if the user was already near the bottom. Never yank the view while he's reading back.

**The mic.** A 72 px circle, bottom centre, the obvious thing to touch.
- Press: scales to 0.94 over `--fast`, a 12 ms haptic (`navigator.vibrate(12)`), and recording starts
  *immediately* — no confirmation, no delay. Hold to talk.
- While recording: the button pulses gently (not a strobe), a live **level meter** driven by
  `AnalyserNode` shows it is really hearing him, and a timer counts up. A real meter, not a fake
  animation — when the mic is muted at the OS level he must be able to see the silence.
- Release: a 20 ms haptic, the button settles, his bubble appears **instantly** in a pending state
  with the timer value, then fills in with the transcript when it arrives.
- Slide the finger ≥ 80 px away before releasing to cancel; show "release to cancel" while in that
  state. Learned from voice notes, and he will try it.
- Text input is always available as a sibling — some turns he'll want to type. One tap to switch, and
  the choice persists.

**The transcript.** Shown in his bubble exactly as the engine returned it, with a small
`transcribed` affordance. If it looks wrong he must be able to tell at a glance that the
*transcriber* erred, not him — a tap offers "that's not what I said" which discards the turn without
polluting the mistake log. (See `docs/STT-FINDINGS.md`: the engine does occasionally tidy his
grammar, and he must be able to see and dispute it.)

**Correction cards.** Collapsed by default, directly under his message: a single amber row,
`2 corrections` plus a chevron. Expanding animates the height over `--base` with `--ease` and never
moves the message above it. Inside, per correction: the wrong fragment struck through, the right
form in `--text`, the one-line English explanation in `--text-dim`, and a small category chip
(`case`, `gender`). Chips are consistently coloured per category across the whole app so the
pattern becomes recognisable over weeks. A "beaten this one" moment (the count going down) deserves
a quiet acknowledgement — one line, no fanfare.

**Tutor audio.** Autoplays on arrival. Per message: replay, and a **slow** toggle that fetches
`speed=slow` from the server. While audio plays, show a thin progress line under the bubble — he
needs to know whether it's still speaking or whether playback failed. If `play()` rejects (iOS), swap
in a tap-to-play button on that message instead of failing silently.

**Hide-text mode.** A toggle in the header. German text renders as a blurred block
(`filter: blur(6px)`, `user-select: none`) with a tap-to-reveal per message. Listening practice is
the point, so the audio controls stay fully available. Setting persists.

**Thinking state.** Three dots in a tutor-shaped bubble, animated. It appears within 100 ms of the
release, so there is never a moment where nothing happened. If the wait exceeds ~6 s, add a quiet
line: "still thinking…". If it exceeds ~20 s, offer cancel.

**Word tap.** Tapping any German word in a tutor message opens a bottom sheet (`--r-lg` top corners,
drag-to-dismiss, backdrop fade): the word, its dictionary form, translation, and **Add to vocab**.
Already-saved words show "in your deck" instead. The sheet must open instantly from cache and fill in
the translation when it arrives — never show an empty sheet with a spinner where the word should be.
Tap targets are whole words; strip punctuation but display the original.

## 5. The other screens

**Write.** A real writing surface: the prompt pinned at the top (collapsible), a generous textarea,
a live word count against the target. On submit, his text is re-rendered with the wrong spans
underlined in amber — tapping one reveals the explanation inline, not in a modal. The improved
version sits below under a clear heading, with changed words highlighted. Two sections, no tabs.
Keep a local draft on every keystroke: losing a paragraph of German to a connection drop would be
infuriating.

**Review.** One card, centred, the German large (28 px). Tap anywhere to flip — the flip is the
interaction, so it must be instant and feel physical (a 150 ms scale-and-fade is enough; a 3D flip
is fine if it doesn't jank). Four rating buttons in a row, full width, each ≥ 52 px, labelled
*Again / Hard / Good / Easy* with the next interval underneath in `--text-dim` ("in 4 days") — that
small honesty makes the scheduler trustworthy. Audio plays automatically on reveal. A progress bar
of the session's queue at the top. The end of a session gets a real, calm summary screen, not a
redirect.

**Drill.** One question at a time, big options, instant per-item feedback — the chosen option turns
`--good` or `--warn` immediately with the explanation sliding in beneath. No timer, no score
counter ticking during the drill. 8 items, a progress dot row at the top so the end is in sight.

**Progress.** The page he opens when he wants to feel like this is working, so make it honest and
legible: where he is in the CEFR path, five skill meters (animate from 0 on first paint, `--slow`),
a 30-day activity strip, top mistakes with a trend arrow, vocab counts. Inline SVG or CSS bars —
no chart library. If the data is thin, say "not enough sessions yet" rather than drawing a confident
line through three points.

## 6. States — the part that gets skipped

Every screen needs all four, and they are not afterthoughts:

- **Empty.** First-ever Talk screen should invite a first sentence, not show a void. First Review
  with no cards: explain where cards come from. Write a real sentence for each, in plain English.
- **Loading.** Skeletons shaped like the content for lists; the typing indicator for a turn. A
  centred spinner on an empty screen is the lazy answer — avoid it.
- **Error.** Human sentence + a retry button that actually retries. Use the server's `detail`.
  A 429/503 reads "the tutor is busy — try again in a minute", never a status code.
  **Nothing he typed or recorded is ever lost to an error.**
- **Offline.** A slim persistent banner, and queued recordings/ratings shown as pending rather than
  failed. The shell must start from the service worker cache with no network at all.

## 7. Motion and haptics

Short and purposeful: `--fast` for presses, `--base` for entrances and expansions, `--slow` only for
first-paint meters. Everything decelerates (`--ease`); nothing bounces. No animation longer than
320 ms, ever.

```css
@media (prefers-reduced-motion: reduce) { *, *::before, *::after {
  animation-duration: .01ms !important; transition-duration: .01ms !important; } }
```

Haptics via `navigator.vibrate` (Android only; iOS ignores it — don't rely on it for feedback):
12 ms on mic press, 20 ms on send, 10 ms on a flashcard rating. Nothing else. Silence is a feature.

## 8. Accessibility and polish

- Contrast ≥ 4.5:1 for body text against its surface — check `--text-dim` on `--surface`, it is the
  one that usually fails.
- Visible focus rings for keyboard use; never `outline: none` without a replacement.
- Semantic HTML, real `<button>`s, `aria-live="polite"` on the message list, `aria-expanded` on the
  correction cards, labels on every icon-only control.
- German text in `<span lang="de">` so a screen reader and the OS pronounce it correctly. This one
  matters here more than in most apps.
- The PWA: `manifest.webmanifest` with `display: standalone`, `theme_color` matching `--bg`,
  portrait, maskable icons, and an `apple-touch-icon`. Installed to the home screen it must have no
  browser chrome and no white flash on launch (set the background colour in the manifest *and* on
  `html`).
- No layout shift as content loads: reserve space for audio controls and correction rows.

## 9. Done means

Open it on a real phone and check, honestly:

- [ ] Nothing requires a second hand or a hover.
- [ ] A full talk turn — press, speak, release, read, listen — feels like one smooth motion.
- [ ] No spinner is the primary content of any screen.
- [ ] The keyboard never hides the thing being typed.
- [ ] Rotating the phone, backgrounding it mid-recording, and losing signal mid-turn all recover.
- [ ] It looks deliberate in both dark and light mode, at 320 px and at 430 px.
- [ ] Installed from the home screen it is indistinguishable from a native app at a glance.
- [ ] Nothing he wrote or said can be lost by any error path.
