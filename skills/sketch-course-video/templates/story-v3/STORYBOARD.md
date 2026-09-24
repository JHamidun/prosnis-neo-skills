# Story v3 — how to build one clip

Format approved from the pilot story (1080×1920, 30 fps, reference brand: Vibe Academy) and generalized for stories cut
from a webinar recording. One agent builds one clip. Never edit `src/` from a per-story build (all stories share it)
and never another clip's folder. Full route: `../../references/webinar-stories.md`.

## 0. Project

```
npm i                                      # or a junction node_modules -> a shared Remotion runtime (same versions)
python tools/render.py bundle              # src -> out/bundle, once (~1–10 min, longer on a loaded machine)
```
`public/fonts/` — Manrope (OFL) static weights; `public/common/` — `logo-dark.svg`, `logo-light.svg`, `music.mp3`
(bed of the CTA scene), `art-bot.png` + `art-bot.traces.json` (drawn with tools/gen_art.py + tools/trace_art.py).
`tools/render.py` copies `public/clips/<id>` into the bundle before every render/still, so a new clip never needs a
re-bundle; only a change in `src/` does.

## 1. Media

`public/clips/<id>/edl.json` (audio pieces, B-roll, crops, caption fixes — schema in the docstring of
`tools/prep_from_recording.py`) → `python tools/prep_from_recording.py --job <webinar job.json> <id>` →
screen.mp4 / result.mp4 (2160×1262 = panel aspect), face.mp4 / result_face.mp4, voice.wav (−16 LUFS), words.json,
media.json (process_dur, result_dur, cuts, piece map), sheet_screen.jpg / sheet_result.jpg (0.1 grid, story time).
Edit the EDL and re-run if a cut is wrong (temp pieces are keyed by content, never stale). Frame counts are exact.

## 2. story.json — every field

Clock: process `0 … process_dur`, result `process_dur … +result_dur`, CTA after;
`frames = round((process_dur + result_dur + 7.5) * 30)`.

- `eyebrow` — where the recording is from («С открытого эфира …»).
- `hook.title` — 2 lines, each ≤ 16 characters, a claim a viewer wants to see proven. `hook.end` — 3.0–4.0 s, cut at
  a pause in `words.json`, never mid-word.
- `title` — the live header, 2 lines ≤ 22 characters, the story's headline in plain words.
- `process.zooms` — 2–4 jump-cut zooms onto the part of the screen the speech is about: `{start, end, rect:[x, y, w, w]}`
  in fractions of the raw screen frame (**w and h equal** — keeps the aspect). Outside zooms the whole frame is shown.
  Pick rects on `sheet_screen.jpg` (grid = tenths).
- `steps` — 2–4 steps, labels ≤ 18 characters, verbs. `active` intervals are contiguous from the first step's word to
  `process_dur`; `spot` = the 2–6 s where the target is visible; `target` = `[x, y, w, h]` in **raw frame fractions**
  (mapped through the active zoom). The word that names the step starts `spot`.
- `sketches` — 1–2 drawn scenes that replace the screen panel for 2.5–4 s: where the speech explains an idea the screen
  cannot show, or where the screen must be hidden (private data). Never over the only moment the real result is visible.
  `draw` ≈ duration − 0.6 s.
- `cta`, `button` — the CTA scene and the clickable story area (one rect for the whole video, the button never
  disappears); verified claims only.
- `words` — `words.json` as is.
- optional (webinar stories): `result` may be absent (idea / invite story); `result.title`, `result.stamp` (default
  РЕЗУЛЬТАТ), `result.zooms` (story clock); `doneText` — tracker text during the result; `cuts` — copy of
  `media.json.cuts` (the face circle alternates framing at every hard cut); `process.faceLabels` — `[{start, end, text}]`
  chip under the face; `callouts`:
  `{type:'chat', start, end, title?, messages:[str|{text,hi}], every?}` anonymous chat bubbles (NO names),
  `{type:'tally', start, end, title, bars:[{label, value, hi?}], note?}`,
  `{type:'stat', start, end, title?, items:[{value, label, prefix?, suffix?, hi?}], note?}` (count-up),
  `{type:'note', start, end, text, x, y, arrow?}` (handwritten note with an arrow).

## 3. Drawings

`public/clips/<id>/art_spec.json`: one `art-hook` (1:1) and one entry per sketch (16:9); `subject` in English: concrete
objects that show the idea of that moment, simple robots/laptops/documents/arrows, no text.

```
python tools/gen_art.py public/clips/<id>/art_spec.json
python tools/trace_art.py public/clips/<id>/art-hook.png paper public/clips/<id>/art-hook.traces.json
```

The style is fixed in `gen_art.py` — GRAPHITE pencil + crosshatching + restrained coral, not navy ink, not vector art
(navy is only the text colour). Look at every PNG: no letters, nothing touching the edge, the idea readable. Regenerate
a bad one by deleting it and rerunning.

## 4. Render and check

```
python tools/render.py still <id> <frame> [<frame> ...]        # proofs -> out/proof/
python tools/render.py render <id> --concurrency 6 --out out/<id>_raw.mp4
python tools/fix_av.py out/<id>_raw.mp4 out/<id>.mp4            # ALWAYS: Remotion AAC priming = audio 42.7 ms late
```

At most two renders at once (lock slots), BELOW_NORMAL, every call retried (headless Chrome misses its start window on
a loaded machine). Look at a contact sheet: the spotlight sits on the thing the voice names; captions never cross the
face; the hook drawing finishes before the cut; the CTA scene is complete; no white line at the bottom (Zoom share
frame at y ≈ 0.964 — base crop `[0.037, 0, 0.96, 0.96]`). Re-check A/V against the source by cross-correlation
(expect 0 ms after fix_av).

## 5. Privacy

Private data never reaches the frame: personal chats, e-mails, phones, logins/passwords, keys, IP addresses, client names
without consent, participants' names in the Zoom strip (never show the strip). If such data is on screen and the speech
needs that moment, cover it with a sketch instead of blurring. Chat callouts are anonymous.

Return: path to the mp4, the zoom/step/sketch decisions in one line each, anything for the owner to decide.
