"""Slides PDF with CLICKABLE videos - "obviously a video, click it" (G-P1), and its external verification.

build: on every video area of the exported PDF (rect from the pptx xfrm, pptx_video_rects.py) - a big centred play
       button (the universal video signifier), a pill "Нажмите, чтобы посмотреть видео · m:ss" (duration from the file)
       in the bottom-right corner (shorter "Смотреть видео · m:ss" when the area is narrow), link annotations over the
       whole area. Two videos in ONE frame get two numbered buttons with captions placed in the gutters of the poster
       (never over its letters) and the frame is split left/right between their links. Pages without video are not
       touched. Link targets = public URLs of the videos (upload_videos_yadisk.py).
verify: page count, links per page == expected URI set, non-video pages pixel-identical to the source PDF (md5 of a
       30 dpi render), anonymous availability of every public link (Yandex Disk public API: 200 + md5 match + download
       href; or plain HTTP 200), PNG renders of chosen pages for a look. Reference run: 45 links on 13 pages, 0 mismatches.

video_links.json: [{"slide": 12, "file": "<original video>.mp4", "rect": [x, y, w, h] (fractions), "public_url": "...",
                    "md5": "<md5 of the file>", ...}]
multi.json (optional, two+ videos in one frame): {"<video file stem>": ["<caption under the button>",
                    "<pill label>", <button x as a fraction of the frame>]} - default: "Видео i", evenly spaced
Font: a STATIC TrueType instance (PyMuPDF cannot use a variable font weight - G-F2/G-F3):
    python -c "from fontTools.ttLib import TTFont; from fontTools.varLib import instancer; \
               f = instancer.instantiateVariableFont(TTFont('Manrope-var.ttf'), {'wght': 700}); f.save('Manrope-Bold-700.ttf')"
usage:
  python pdf_video_links.py build  <src.pdf> <video_links.json> <out.pdf> --font <ttf> [--multi multi.json]
                                   [--accent F26941] [--title "…"] [--author "…"] [--subject "…"] [--expect-pages 76]
  python pdf_video_links.py verify <out.pdf> <src.pdf> <video_links.json> [--anon yadisk|http|none] [--renders DIR --pages 7,12]
"""
import hashlib
import json
import pathlib
import subprocess
import sys

import fitz  # PyMuPDF

WHITE = (1, 1, 1)
BLACK = (0, 0, 0)
DARK = (0.08, 0.08, 0.08)
LONG_LABEL = 'Нажмите, чтобы посмотреть видео'
SHORT_LABEL = 'Смотреть видео'


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                         capture_output=True, text=True, check=True).stdout.strip()
    s = round(float(out))
    return f'{s // 60}:{s % 60:02d}'


def minus(r, c):
    """Rect r minus rect c as up to 4 non-overlapping rects."""
    c = fitz.Rect(c) & r
    if c.is_empty:
        return [fitz.Rect(r)]
    parts = [fitz.Rect(r.x0, r.y0, r.x1, c.y0), fitz.Rect(r.x0, c.y1, r.x1, r.y1),
             fitz.Rect(r.x0, c.y0, c.x0, c.y1), fitz.Rect(c.x1, c.y0, r.x1, c.y1)]
    return [p for p in parts if p.width > 2 and p.height > 2]


class Painter:
    def __init__(self, font_file, accent):
        self.font_file = font_file
        self.font = fitz.Font(fontfile=font_file)
        self.accent = accent

    def pill_width(self, label, fs, icon=True):
        return fs * 0.95 * 2 + (fs * 0.8 * 0.9 + fs * 0.55 if icon else 0) + self.font.text_length(label, fontsize=fs)

    def pill(self, page, r, label, fs, fill=None, icon=True):
        fill = self.accent if fill is None else fill
        rad = r.height / 2
        sh = page.new_shape()
        sh.draw_rect(r + (1.2, 1.8, 1.2, 1.8), radius=(rad / r.width, 0.5))
        sh.finish(color=None, fill=BLACK, fill_opacity=0.35)
        sh.commit()
        sh = page.new_shape()
        sh.draw_rect(r, radius=(rad / r.width, 0.5))
        sh.finish(color=WHITE, width=1, fill=fill, fill_opacity=1)
        x = r.x0 + fs * 0.95
        cy = (r.y0 + r.y1) / 2
        if icon:
            tri = fs * 0.8
            sh.draw_polyline([fitz.Point(x, cy - tri / 2), fitz.Point(x + tri * 0.9, cy), fitz.Point(x, cy + tri / 2), fitz.Point(x, cy - tri / 2)])
            sh.finish(color=None, fill=WHITE, closePath=True)
            x += tri * 0.9 + fs * 0.55
        sh.insert_text(fitz.Point(x, cy + fs * 0.36), label, fontname='manb', fontsize=fs, color=WHITE)
        sh.commit()

    def play_button(self, page, c, d):
        r = d / 2
        sh = page.new_shape()
        sh.draw_circle(c + (1.5, 2.5), r + 1)                     # drop shadow
        sh.finish(color=None, fill=BLACK, fill_opacity=0.40)
        sh.commit()
        sh = page.new_shape()
        sh.draw_circle(c, r)
        sh.finish(color=WHITE, width=max(2.0, d * 0.045), fill=self.accent, fill_opacity=0.95)
        t = d * 0.40                                               # triangle height
        ox = d * 0.05                                              # optical centring
        sh.draw_polyline([fitz.Point(c.x - t * 0.42 + ox, c.y - t / 2), fitz.Point(c.x + t * 0.58 + ox, c.y),
                          fitz.Point(c.x - t * 0.42 + ox, c.y + t / 2), fitz.Point(c.x - t * 0.42 + ox, c.y - t / 2)])
        sh.finish(color=None, fill=WHITE, closePath=True)
        sh.commit()


def build():
    src_pdf, links_p, out_pdf = sys.argv[2], sys.argv[3], pathlib.Path(sys.argv[4])
    font_file = arg('--font')
    if not font_file:
        raise SystemExit('--font <static ttf> is required (see the docstring)')
    acc = arg('--accent', 'F26941')
    P = Painter(font_file, tuple(int(acc[i:i + 2], 16) / 255 for i in (0, 2, 4)))
    multi_labels = json.load(open(arg('--multi'), encoding='utf-8')) if arg('--multi') else {}
    links = json.load(open(links_p, encoding='utf-8'))
    missing = [e for e in links if not e.get('public_url')]
    if missing:
        raise SystemExit(f'{len(missing)} videos without public_url in {links_p}')
    doc = fitz.open(src_pdf)
    if arg('--expect-pages') and doc.page_count != int(arg('--expect-pages')):
        raise SystemExit(f'{src_pdf}: {doc.page_count} pages, expected {arg("--expect-pages")}')
    by_page = {}
    for e in links:
        e['duration'] = duration(e['file'])
        by_page.setdefault(e['slide'], []).append(e)
    report = []
    for pno, items in sorted(by_page.items()):
        page = doc[pno - 1]
        page.insert_font(fontname='manb', fontfile=font_file)
        W, H = page.rect.width, page.rect.height
        groups = {}  # videos sharing one on-slide rect (e.g. a sequence and then a grid in the same frame)
        for e in items:
            groups.setdefault(tuple(e['rect']), []).append(e)
        for rect_frac, vids in groups.items():
            x, y, w, h = rect_frac
            area = fitz.Rect(x * W, y * H, (x + w) * W, (y + h) * H)
            full = w > 0.98 and h > 0.98
            multi = len(vids) > 1
            margin = 16 if full else 9
            fs = 13 if full else 11.5
            bh = fs * 2.3
            gap = 6

            def ml(e, k):
                stem = pathlib.Path(e['file']).stem
                n = len(vids)
                i = vids.index(e)
                default = (f'Видео {i + 1}', f'Видео {i + 1}', (i + 0.5) / n)
                return (multi_labels.get(stem) or default)[k]

            badges = []  # corner pills, stacked bottom-up, right-aligned inside the video area
            ybot = area.y1 - margin
            for e in reversed(vids):
                if multi:
                    label = f"{ml(e, 1)} · {e['duration']}"
                else:
                    label = f"{LONG_LABEL} · {e['duration']}"
                    if P.pill_width(label, fs) > area.width - 2 * margin:
                        label = f"{SHORT_LABEL} · {e['duration']}"
                bw = P.pill_width(label, fs)
                r = fitz.Rect(area.x1 - margin - bw, ybot - bh, area.x1 - margin, ybot)
                badges.append((r, label, e))
                ybot = r.y0 - gap
            badges.reverse()
            for r, label, e in badges:
                P.pill(page, r, label, fs)
            col = fitz.Rect(min(b[0].x0 for b in badges), min(b[0].y0 for b in badges), area.x1, area.y1)
            d = max(46, min(88, 0.24 * min(area.width, area.height)))  # big play button(s) in the middle
            cy = area.y0 + area.height / 2
            centres = [fitz.Point(area.x0 + area.width * ml(e, 2), cy) for e in vids] if multi else [fitz.Point(area.x0 + area.width / 2, cy)]
            for c, e in zip(centres, vids):
                P.play_button(page, c, d)
                if multi:  # caption under each button
                    cap = ml(e, 0)
                    cfs = 11.5
                    cw = P.pill_width(cap, cfs, icon=False)
                    top = c.y + d / 2 + 7
                    P.pill(page, fitz.Rect(c.x - cw / 2, top, c.x + cw / 2, top + cfs * 2.2), cap, cfs, fill=DARK, icon=False)
            for r, label, e in badges:  # links: pills -> own video; the rest of the frame -> its video (split when several)
                page.insert_link({'kind': fitz.LINK_URI, 'from': r, 'uri': e['public_url']})
            n = len(vids)
            for p in minus(area, col):
                for i, e in enumerate(vids):
                    sx0 = area.x0 + area.width * i / n
                    sx1 = area.x0 + area.width * (i + 1) / n
                    q = fitz.Rect(max(p.x0, sx0), p.y0, min(p.x1, sx1), p.y1)
                    if q.width > 2 and q.height > 2:
                        page.insert_link({'kind': fitz.LINK_URI, 'from': q, 'uri': e['public_url']})
            report.append((pno, [pathlib.Path(v['file']).name for v in vids], [round(c) for c in area], round(d), [b[1] for b in badges]))
    meta = dict(doc.metadata)
    for k in ('title', 'author', 'subject'):
        if arg(f'--{k}'):
            meta[k] = arg(f'--{k}')
    doc.set_metadata(meta)
    doc.save(out_pdf, garbage=3, deflate=True)
    for r in report:
        print(r)
    print('saved', out_pdf, out_pdf.stat().st_size)


def verify():
    out_pdf, src_pdf, links_p = sys.argv[2], sys.argv[3], sys.argv[4]
    links = json.load(open(links_p, encoding='utf-8'))
    doc, src = fitz.open(out_pdf), fitz.open(src_pdf)
    print('pages', doc.page_count, 'src pages', src.page_count)
    expected = {}
    for e in links:
        expected.setdefault(e['slide'], set()).add(e['public_url'])
    bad = 0
    n_links = 0
    for i, page in enumerate(doc, 1):
        ls = page.get_links()
        n_links += len(ls)
        uris = {l.get('uri') for l in ls}
        if i in expected or ls:
            ok = uris == expected.get(i, set())
            bad += not ok
            print(f'p{i:02d} links={len(ls)} {"OK" if ok else "MISMATCH expected " + str(sorted(expected.get(i, set())))}')
    print('links total', n_links, 'on', len(expected), 'pages; link mismatches:', bad)
    diff = 0
    for i in range(doc.page_count):
        if (i + 1) in expected:
            continue
        a = doc[i].get_pixmap(dpi=30).samples
        b = src[i].get_pixmap(dpi=30).samples
        diff += hashlib.md5(a).digest() != hashlib.md5(b).digest()
    print('non-video pages differing from source:', diff)
    fails = 0
    mode = arg('--anon', 'yadisk')
    if mode != 'none':
        import requests
        for e in links:
            if mode == 'yadisk':
                r = requests.get('https://cloud-api.yandex.net/v1/disk/public/resources',
                                 params={'public_key': e['public_url'], 'fields': 'name,size,md5,media_type'}, timeout=60)
                j = r.json() if r.content else {}
                d = requests.get('https://cloud-api.yandex.net/v1/disk/public/resources/download', params={'public_key': e['public_url']}, timeout=60)
                w = requests.get(e['public_url'], timeout=60, allow_redirects=True)
                ok = r.status_code == 200 and (not e.get('md5') or j.get('md5') == e['md5']) and d.status_code == 200 and w.status_code == 200
                e['check'] = dict(api=r.status_code, md5_match=j.get('md5') == e.get('md5'), download_href=d.status_code, page=w.status_code)
            else:
                w = requests.get(e['public_url'], timeout=60, allow_redirects=True)
                ok = w.status_code == 200
                e['check'] = dict(page=w.status_code)
            fails += not ok
            print(f"p{e['slide']:02d} {'OK' if ok else 'FAIL'} {e['check']} {e['public_url']}")
        print('link failures:', fails)
        pathlib.Path(links_p).with_suffix('.checked.json').write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    if arg('--renders'):
        d = pathlib.Path(arg('--renders'))
        d.mkdir(parents=True, exist_ok=True)
        for p in [int(x) for x in (arg('--pages') or '').split(',') if x]:
            doc[p - 1].get_pixmap(dpi=110).save(d / f'out_p{p:02d}.png')
        print('renders ->', d)
    sys.exit(1 if bad or diff or fails else 0)


if __name__ == '__main__':
    if len(sys.argv) < 5 or sys.argv[1] not in ('build', 'verify'):
        raise SystemExit(__doc__)
    build() if sys.argv[1] == 'build' else verify()
