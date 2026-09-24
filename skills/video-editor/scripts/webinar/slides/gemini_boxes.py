"""S7: semantic element boxes + spoken cue words + marks + margin note + key phrase for ONE slide (Gemini vision).

The EDL builder turns this into (b) live-sketch beats, (c) marks inside the slide, (d) doodles around it and quote
accents (references/webinar-montage.md, S8). prep_slides.py calls ask() for every SHOWN slide; this file is also a
CLI for a single slide (showcases, re-asking one slide after a manual check).

usage:
  python gemini_boxes.py --job job.json <slide_no> <src_id> <t_in> <t_out> [<src_id> <t_in> <t_out> ...] [--force]
      -> edl/boxes/boxes_NNN.json (skip-if-done unless --force)
Image: remotion/public/full/slides/NNN.png (clean PDF render, prep_slides.py render).
Words: transcript/<src_id>.words.json (or transcript.words_files{src_id: path} in job.json).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()

PROMPT = """You see ONE slide (1920x1080) of a Russian webinar deck (hand-drawn exec-sketch style or screenshots),
and the words the host said while this slide was on screen (with start times in seconds).

Task A — split the slide into 3-9 SEMANTIC ELEMENTS in natural reading/drawing order (title first).
An element is a visually separate group: the title line, one illustration with its caption, one numbered item,
a screenshot, a footer call-to-action, etc. Boxes must be tight but include the whole group (drawing + its label),
must not overlap each other much, and together should cover every ink mark on the slide.
Task B — for each element find the EXACT words (copied from the transcript, 1-4 consecutive words) at the moment
the host first names or explains that element; null if never mentioned.
Task C — suggest ONE hand-drawn emphasis for elements worth it: "circle" (ellipse around a label/number),
"underline" (under a text line), "check" (tick next to an item), "arrow" (arrow pointing at it from outside),
"pulse" (gentle pulse of the element), or "none". At most 3 non-none marks per slide, only where the host
really stresses the point. mark_box_2d = the exact text/number the mark goes around/under (tight).
Task D — margin_note: ONE short handwritten margin note in Russian (2-5 words) that repeats or compresses what the
host SAID about this slide (never a new fact, never a number that was not said or written), the element id it points
at, and the exact transcript words (1-4) when he says it. null if nothing fits.
Task E — key_phrase: the host's single strongest short phrase (<= 60 chars, copied verbatim from the transcript) said
on this slide that is NOT written on the slide; its first 2-4 words exactly as in the transcript; the one word to
colour. null if none is really strong.
Task F — empty_corners: which slide corners (tl, tr, bl, br) have no text or drawing within ~260x110 px.

Return JSON only:
{"elements":[{"id":"e1","label":"short russian label","kind":"title|text|illustration|item|number|screenshot|footer",
"box_2d":[ymin,xmin,ymax,xmax], "cue_words":"..." or null, "mark":"circle|underline|check|arrow|pulse|none",
"mark_box_2d":[ymin,xmin,ymax,xmax] or null}],
 "margin_note": {"text":"...","element":"e2","cue_words":"..."} or null,
 "key_phrase": {"text":"...","start_words":"...","em":"..."} or null,
 "empty_corners": ["tl","br"]}
All boxes are integers 0..1000 relative to the slide (y first).
"""

MODEL = J.get('slides.model', J.get('vision.model', 'gemini-3.8-flash'))
BOX = J.p('edl/boxes')
SLIDES = J.p('remotion/public/full/slides')


def words_of(src: str) -> list:
    files = J.get('transcript.words_files', {}) or {}
    path = J.rel(files[src]) if src in files else J.p(f'transcript/{src}.words.json')
    return json.load(open(path, encoding='utf-8'))['words']


_WORDS: dict = {}


def transcript_text(windows) -> str:
    """'(part1 213.1-274.7) [213.2] w w w w w w w w [216.2] ...' - a timestamp every 8 words (the reference format)."""
    chunks = []
    for src, a, b in windows:
        if src not in _WORDS:
            _WORDS[src] = words_of(src)
        ws = [w for w in _WORDS[src] if a <= w['start'] <= b]
        body = ' '.join(f"[{w['start']:.1f}] {w['punctuated_word']}" if i % 8 == 0 else w['punctuated_word']
                        for i, w in enumerate(ws))
        chunks.append(f'({src} {a:.1f}-{b:.1f}) {body}')
    return '\n'.join(chunks)


def ask(client, n: int, windows, tx: str | None = None, force=False, attempts=3):
    """One slide -> edl/boxes/boxes_NNN.json. Returns 'skip' | 'ok' | 'FAIL <err>'."""
    from google.genai import types
    out = f'{BOX}/boxes_{n:03d}.json'
    if os.path.exists(out) and not force:
        return 'skip'
    os.makedirs(BOX, exist_ok=True)
    img = open(f'{SLIDES}/{n:03d}.png', 'rb').read()
    tx = tx if tx is not None else transcript_text(windows)
    last = None
    for attempt in range(attempts):
        try:
            r = client.models.generate_content(
                model=MODEL,
                contents=[types.Part.from_bytes(data=img, mime_type='image/png'), PROMPT + '\nTRANSCRIPT:\n' + tx],
                config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0.2,
                                                   thinking_config=types.ThinkingConfig(thinking_level='high')),
            )
            data = json.loads(r.text)
            data['slide'] = n
            data['window'] = [list(w) for w in windows]
            tmp = out + '.part'
            with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, out)
            return 'ok'
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:200]
            time.sleep(4 + attempt * 6)
    return 'FAIL ' + str(last)


def main():
    args = [a for a in sys.argv[1:] if a != '--force']
    force = '--force' in sys.argv
    if len(args) < 4 or (len(args) - 1) % 3:
        raise SystemExit(__doc__)
    n = int(args[0])
    windows = [(args[i], float(args[i + 1]), float(args[i + 2])) for i in range(1, len(args), 3)]
    client = J.gemini()
    st = ask(client, n, windows, force=force)
    print(n, st)
    if st == 'ok' or st == 'skip':
        print(open(f'{BOX}/boxes_{n:03d}.json', encoding='utf-8').read()[:3000])


if __name__ == '__main__':
    main()
