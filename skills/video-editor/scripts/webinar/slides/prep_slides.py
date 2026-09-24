"""S7: slides for the Program - clean PDF renders + clean deck art + Gemini boxes for every SHOWN slide.

Never take the blurry Zoom share of a slide into the montage: the Program always shows the clean slide (style.md §4).

Outputs (skip-if-done everywhere):
  remotion/public/full/slides/NNN.png   PDF render 1920 px wide (what was on screen)
  remotion/public/full/art/NNN.png      clean deck art (only slides that have art: deck.art_map / deck.merged.json)
  edl/boxes_jobs.json                   shown slides: windows [src, t_in, t_out] + transcript of those windows
  edl/boxes/boxes_NNN.json              Gemini: elements, cue words, marks, margin note, key phrase, empty corners

job.json:
  deck.pdf        the slides PDF (the file that was presented)
  deck.art_dir    folder of clean art; deck.art_map = json {"<slide>": "<png relative to art_dir>"} OR
  deck.merged     exec-sketch deck.merged.json (manus-slides): slides[i].binding.image relative to its folder
  slides.extra_windows   [[slide, src, t_in, t_out], ...] - windows the vision pass cannot see (e.g. the
                         recorder-only intro before the Zoom recording started)
  slides.workers  parallel Gemini calls (default 10)
  slides.min_window_s  scene segments shorter than this are not windows (rapid flips; default 3.0)
usage: python prep_slides.py --job job.json [render|jobs|boxes|all]
"""
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from job import load  # noqa: E402

J = load()
import gemini_boxes as GB  # noqa: E402

PUB = Path(J.p('remotion/public/full'))
BOX = Path(J.p('edl/boxes'))
MIN_WIN = float(J.get('slides.min_window_s', 3.0))


def art_map() -> dict:
    """{slide_no: absolute png path} from deck.art_map or deck.merged (binding.image)."""
    out = {}
    if J.get('deck.art_map'):
        base = Path(J.rel(J.get('deck.art_dir') or '.'))
        for k, v in json.load(open(J.rel(J.get('deck.art_map')), encoding='utf-8')).items():
            out[int(k)] = base / v
    elif J.get('deck.merged'):
        mp = Path(J.rel(J.get('deck.merged')))
        merged = json.load(open(mp, encoding='utf-8'))
        for i, s in enumerate(merged['slides'], 1):
            img = (s.get('binding') or {}).get('image')
            if img:
                out[i] = mp.parent / img
    return out


def render():
    import fitz  # PyMuPDF
    d = PUB / 'slides'
    d.mkdir(parents=True, exist_ok=True)
    a = PUB / 'art'
    a.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(J.rel(J.need('deck.pdf')))
    arts = art_map()
    print('pdf pages', len(doc))
    for n in range(1, len(doc) + 1):
        out = d / f'{n:03d}.png'
        if not out.exists():
            page = doc[n - 1]
            z = 1920 / page.rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            pix.save(str(out))
        src = arts.get(n)
        if src and src.exists():
            dst = a / f'{n:03d}.png'
            if not dst.exists():
                shutil.copy2(src, dst)
    print('render OK', len(list(d.glob('*.png'))), 'slides', len(list(a.glob('*.png'))), 'art')


def jobs():
    """Shown slides from vision/scenes.json (slide_number of every segment) + slides.extra_windows."""
    scenes = json.load(open(J.p('vision/scenes.json'), encoding='utf-8'))
    tags = J.vision_tags()  # {'P1': 'part1', ...}
    per: dict = {}
    order = []
    for extra in J.get('slides.extra_windows', []) or []:
        n, src, a, b = int(extra[0]), extra[1], float(extra[2]), float(extra[3])
        per.setdefault(n, []).append((src, a, b))
        order.append((n, 0, a))
    for ti, (tag, sid) in enumerate(tags.items(), 1):
        for seg in scenes['sources'][tag]['segments']:
            n = seg.get('slide_number')
            if not n or seg.get('screen_content') not in ('slide', None) and seg.get('share_kind') != 'slides':
                continue
            n = int(n)
            w = (sid, round(seg['src_in'], 2), round(seg['src_out'], 2))
            if w[2] - w[1] < MIN_WIN:  # rapid flips (G-V4) carry no speech about the slide
                continue
            per.setdefault(n, []).append(w)  # one window per scene segment (the reference format)
            order.append((n, ti, w[1]))
    out = []
    for n in sorted(per):
        windows = per[n]
        out.append({'slide': n, 'window': [list(w) for w in windows], 'tx': GB.transcript_text(windows)})
    p = J.p('edl/boxes_jobs.json')
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('jobs', len(out), 'shown slides ->', p)
    return out


def boxes():
    BOX.mkdir(parents=True, exist_ok=True)
    p = J.p('edl/boxes_jobs.json')
    todo = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else jobs()
    client = J.gemini()
    workers = int(J.get('slides.workers', 10))

    def one(job):
        return job['slide'], GB.ask(client, job['slide'], [tuple(w) for w in job['window']], tx=job['tx'])

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for n, st in ex.map(one, todo):
            print('boxes', n, st, flush=True)
    print('BOXES_DONE')


if __name__ == '__main__':
    what = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if what in ('render', 'all'):
        render()
    if what in ('jobs', 'all'):
        jobs()
    if what in ('boxes', 'all'):
        boxes()
