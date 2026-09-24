"""S7/S8 (b): stroke masks for the LIVE SKETCH reveal of a whole deck slide, element by element.

Reuses the approved engine of the sibling skill sketch-course-video (scripts/trace.py: skeleton centre-lines of the
ORIGINAL raster + accent hatching; the original PNG bytes are never modified - Remotion's SketchReveal opens the
original raster through an SVG mask drawn with strokeDashoffset).
Deck palette handled here: dark slides = black bg / white ink / yellow accent (+ red/blue pills, coral),
paper slides = #F8F3EC-like bg / dark ink / yellow accent. Grey fills of dark slides are a separate "shade" mask that
the finish fade reveals (never traced as strokes).

Text-bearing elements (everything except illustration/screenshot/rest) are ordered left -> right at trace time
(order_strokes(..., lettering=True), G-S1); SketchReveal.pathsOf() re-times them left -> right with 35 % overlap
anyway, so a handwritten caption is never revealed as scattered letters. --no-lettering reproduces the reference run
(contour order for every element).

Input : remotion/public/full/art/NNN.png (clean art), edl/boxes/boxes_NNN.json (gemini_boxes / prep_slides)
Output: remotion/public/full/sketch/NNN.json  {slide, src, w, h, theme, bg, elements[{id,label,kind,crop,paths[{d,w,s,u,c}],
        finish, ink_px, acc_px}]} - the catch-all element "rest" (ink outside every semantic box) comes last.
usage:
  python sketch_slide.py --job job.json <slide_no> [dark|paper] [--no-lettering]
  python sketch_slide.py --job job.json all [--workers 8]      every art slide that has boxes (skip-if-done, BELOW_NORMAL)
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load, low_flags  # noqa: E402

J = load()
PUB = Path(J.p('remotion/public/full'))
TEXT_KINDS_EXCLUDED = {'illustration', 'screenshot', 'rest'}


def _engine():
    sys.path.insert(0, J.skill('sketch-course-video') + '/scripts')
    from trace import trace_paths, order_strokes, color_paths  # noqa: E402
    return trace_paths, order_strokes, color_paths


def clean(mask, minimum=6):
    import cv2
    import numpy as np
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(count, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= minimum
    return keep[labels]


def split(crop, dark):
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    chroma = crop.max(axis=2) - crop.min(axis=2)
    yellow = (r > 155) & (g > 110) & ((r - b) > 55)
    other = (chroma > 70) & ~yellow  # red/blue pills, coral, etc.
    if dark:
        ink = (crop.min(axis=2) > 82) & (chroma < 85)
        shade = (crop.min(axis=2) > 40) & (chroma < 60) & ~ink  # grey fills: revealed by the finish fade
    else:
        import numpy as np
        ink = (crop.mean(axis=2) < 170) & (chroma < 90) & ~yellow
        shade = np.zeros(ink.shape, dtype=bool)
    return clean(ink), clean(yellow | other), clean(shade, 20)


def finish_path(mask, x, y):
    import cv2
    import numpy as np
    grown = cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(grown, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        if cv2.contourArea(c) < 3:
            continue
        pts = cv2.approxPolyDP(c, .6, True).reshape(-1, 2)
        out.append('M' + ' L'.join(f'{a + x},{b + y}' for a, b in pts) + 'Z')
    return ' '.join(out)


def pd(points):
    return 'M' + ' L'.join(f'{p[0]:.1f},{p[1]:.1f}' for p in points)


def element(img, box, dark, keep=None, lettering=False):
    trace_paths, order_strokes, color_paths = _engine()
    x, y, w, h = box
    crop = img[y:y + h, x:x + w].astype(float)
    ink, acc, shade = split(crop, dark)
    if keep is not None:  # catch-all element: only ink outside every semantic box
        k = keep[y:y + h, x:x + w]
        ink, acc, shade = ink & k, acc & k, shade & k
    outlines = order_strokes(trace_paths(ink, x, y), lettering=lettering)
    fill = color_paths(acc, x, y)
    paths = []
    for group, portion, offset, color in [(outlines, .74, 0.0, 0), (fill, .24, .76, 1)]:
        total = sum(max(p['length'], 12) for p in group) or 1
        cur = offset
        for p in group:
            dur = portion * max(p['length'], 12) / total
            paths.append({'d': pd(p['points']), 'w': round(p['width'], 1), 's': round(cur, 4), 'u': round(dur, 4), 'c': color})
            cur += dur
    return {'crop': [x, y, w, h], 'paths': paths, 'finish': finish_path(ink | acc | shade, x, y),
            'ink_px': int(ink.sum()), 'acc_px': int(acc.sum())}


def one(n: int, theme: str | None = None, lettering=True):
    import cv2
    import numpy as np
    raw = cv2.imdecode(np.fromfile(str(PUB / f'art/{n:03d}.png'), dtype=np.uint8), cv2.IMREAD_COLOR)
    img = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
    H, W = img.shape[:2]
    theme = theme or ('dark' if img.mean() < 110 else 'paper')
    dark = theme == 'dark'
    boxes = json.load(open(J.p(f'edl/boxes/boxes_{n:03d}.json'), encoding='utf-8'))
    els = []
    for e in boxes['elements']:
        y0, x0, y1, x1 = e['box_2d']
        pad = 10
        bx = max(0, int(x0 / 1000 * W) - pad)
        by = max(0, int(y0 / 1000 * H) - pad)
        bw = min(W, int(x1 / 1000 * W) + pad) - bx
        bh = min(H, int(y1 / 1000 * H) + pad) - by
        d = element(img, (bx, by, bw, bh), dark, lettering=lettering and e.get('kind') not in TEXT_KINDS_EXCLUDED)
        d.update({'id': e['id'], 'label': e['label'], 'kind': e['kind']})
        els.append(d)
        print(e['id'], e['label'], len(d['paths']), 'strokes', d['ink_px'], d['acc_px'])
    covered = np.zeros((H, W), dtype=bool)
    for d in els:
        x, y, w, h = d['crop']
        covered[y:y + h, x:x + w] = True
    rest = element(img, (0, 0, W, H), dark, keep=~covered)
    if rest['paths']:
        rest.update({'id': 'rest', 'label': 'остальное', 'kind': 'rest'})
        els.append(rest)
        print('rest', len(rest['paths']), 'strokes', rest['ink_px'], rest['acc_px'])
    out = PUB / f'sketch/{n:03d}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    border = np.concatenate([img[:8].reshape(-1, 3), img[-8:].reshape(-1, 3), img[:, :8].reshape(-1, 3), img[:, -8:].reshape(-1, 3)])
    bg = '#%02X%02X%02X' % tuple(int(v) for v in np.median(border, axis=0))
    tmp = out.with_suffix('.json.part')
    tmp.write_text(json.dumps({'slide': n, 'src': f'full/art/{n:03d}.png', 'w': W, 'h': H, 'theme': theme, 'bg': bg,
                               'elements': els}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8', newline='\n')
    os.replace(tmp, out)
    print('OK', out, round(out.stat().st_size / 1e6, 2), 'MB')


def run_all(workers=8, extra=()):
    """Every art slide with boxes -> child process at BELOW_NORMAL (numpy/cv2 loops are heavy)."""
    arts = sorted(int(p.stem) for p in (PUB / 'art').glob('*.png'))

    def job(n):
        out = PUB / f'sketch/{n:03d}.json'
        if out.exists():
            return n, 'skip'
        if not Path(J.p(f'edl/boxes/boxes_{n:03d}.json')).exists():
            return n, 'nobox'
        r = subprocess.run([sys.executable, os.path.abspath(__file__), '--job', str(J.file), str(n), *extra],
                           capture_output=True, text=True, **low_flags())
        return n, ('ok' if r.returncode == 0 else 'FAIL ' + r.stderr[-300:])

    with ThreadPoolExecutor(workers) as ex:
        for n, s in ex.map(job, arts):
            print(n, s, flush=True)
    print('SKETCH_DONE')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a not in ('--no-lettering',)]
    lettering = '--no-lettering' not in sys.argv
    if not args:
        raise SystemExit(__doc__)
    if args[0] == 'all':
        w = int(args[args.index('--workers') + 1]) if '--workers' in args else 8
        run_all(w, () if lettering else ('--no-lettering',))
    else:
        one(int(args[0]), args[1] if len(args) > 1 else None, lettering)
