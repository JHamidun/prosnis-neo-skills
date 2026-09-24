"""Pieces of the sources in broadcast order, cuts, chapter-card insert points and the output clock (S10 steps 1-2).

edl_config.json:
  ranges   [[src, t_in, t_out], ...]                 kept source ranges in broadcast order
  cuts     {src: [cut, ...]} a cut is one of
             {"gap": [a, b], "keep": 0.45, "note": "..."}      silent gap between word ends a..b; keep room tone each side
             {"words": [[a, b, "^regex$", shift_s], [a, b, "^regex", shift_s]], "note": "..."}
                                                              fumble: from the first word matching regex 1 (+shift)
                                                              to the first word matching regex 2 (+shift)
             {"abs": [a, b], "note": "..."}                    absolute source times
  chapters [{"n": 2, "src": "part1", "t": 213.12, "lines": ["…", "…"], "note": "…" | null, "art_slide": 14 | null,
             "art_ids": ["e4"] (optional: which sketch element draws on the card)}]
           chapter 1 opens the broadcast (after the teaser); the others land in the largest speech gap before t.
"""
from __future__ import annotations


def cut_span(X, part, c):
    if 'gap' in c:
        a, b = c['gap']
        keep = c.get('keep', 0.45)
        return (a + keep, b - keep)
    if 'words' in c:
        (a0, b0, rx0, s0), (a1, b1, rx1, s1) = c['words']
        w0 = X.find_word(part, a0, b0, rx0)
        w1 = X.find_word(part, a1, b1, rx1)
        if w0 is None or w1 is None:
            raise SystemExit(f'cut {c}: word not found in {part} (fix the regex/window in edl_config.json)')
        return (w0['start'] + s0, w1['start'] + s1)
    return tuple(c['abs'])


def cuts(X):
    return {part: [cut_span(X, part, c) for c in lst] for part, lst in (X.cfg.get('cuts') or {}).items()}


def cut_notes(X):
    return {part: [c.get('note', '') for c in lst] for part, lst in (X.cfg.get('cuts') or {}).items()}


def chapters(X):
    return [(c['n'], c['src'], c['t'], c['lines'], c.get('note'), c.get('art_slide')) for c in X.cfg['chapters']]


def best_gap(X, part, t, win=5.0):
    """source time inside the largest speech gap in [t-win, t+0.6] (the chapter card lands just BEFORE the slide
    change, so the new slide appears when the card folds away)"""
    ws = X.words_between(part, t - win - 3, t + 3)
    best = None
    for a, b in zip(ws, ws[1:]):
        mid = (a['end'] + b['start']) / 2
        if not (t - win <= mid <= t + 0.6):
            continue
        g = b['start'] - a['end']
        sc = g - 0.03 * abs(mid - t)
        if best is None or sc > best[0]:
            best = (sc, a['end'] + min(0.25, g / 2), g)
    return (best[1], best[2]) if best else (t, 0.0)


def chapter_points(X):
    ins = {}
    for n, part, t, *_ in chapters(X):
        if n == 1:
            continue
        tt, g = best_gap(X, part, t)
        ins.setdefault(part, []).append((X.snap(tt), n, g))
    return ins


def build_pieces(X, CUTS):
    """-> list of dict(src, t0, t1) and chapter insert markers dict(chapter=n) in output order"""
    ins = chapter_points(X)
    seq = [{'chapter': 1}]
    for part, a, b in X.cfg['ranges']:
        a, b = X.snap(a), X.snap(b)
        cs = sorted((X.snap(x), X.snap(y)) for x, y in CUTS.get(part, []))
        spans = []
        cur = a
        for x, y in cs:
            spans.append((cur, x))
            cur = y
        spans.append((cur, b))
        points = sorted(ins.get(part, []))
        for s0, s1 in spans:
            cur = s0
            for tt, n, g in points:
                if s0 < tt < s1:
                    seq.append({'src': part, 't0': cur, 't1': tt, 'join': 'chapter'})
                    seq.append({'chapter': n, 'gap_s': round(g, 2)})
                    cur = tt
            seq.append({'src': part, 't0': cur, 't1': s1})
    return seq


class Clock:
    """source time -> output frame over the kept pieces (times inside a cut map to the next kept frame)."""

    def __init__(self, fps):
        self.fps = fps
        self.segs = []  # (src, t0, t1, f0, f1)

    def add(self, src, t0, t1, f0):
        n = int(round((t1 - t0) * self.fps))
        self.segs.append((src, t0, t0 + n / self.fps, f0, f0 + n))
        return f0 + n

    def f(self, src, t, clamp=True):
        best = None
        for s, t0, t1, f0, f1 in self.segs:
            if s != src:
                continue
            if t0 - 1e-6 <= t < t1 + 1e-6:
                return min(f1 - 1, f0 + int(round((t - t0) * self.fps)))
            if clamp and t < t0 and (best is None or t0 < best[0]):
                best = (t0, f0)
        if best is not None and clamp:
            return best[1]
        return None

    def inside(self, src, t):
        return any(s == src and t0 - 1e-6 <= t < t1 + 1e-6 for s, t0, t1, *_ in self.segs)

    def spans(self, src, a, b):
        """list of (f0, f1, t0) output spans covering source [a,b)"""
        out = []
        for s, t0, t1, f0, f1 in self.segs:
            if s != src or t1 <= a or t0 >= b:
                continue
            x0, x1 = max(a, t0), min(b, t1)
            out.append((f0 + int(round((x0 - t0) * self.fps)), f0 + int(round((x1 - t0) * self.fps)), x0))
        return out


def screen_runs(X):
    """per source: list of (t0, t1, kind, slide). kind: slide | demo | drum | speaker | black
    edl_config.json:
      screen_runs_extra  {src: [[t0, t1, "slide", n], ...]}   sources without a vision pass (recorder-only intro)
      scene_kinds        {"live_demo": "demo", "raffle_app": "drum", "camera": "speaker"}  (screen_content -> kind)
      screen_fixups      [{"src": "part2", "from": 364.0, "to": 366.8, "slide": 27}]     frame-checked slide flips
      black_to_slide     {"part2": 76}   black screen while the share stops: hold that slide"""
    C = X.cfg
    kinds = C.get('scene_kinds', {'live_demo': 'demo', 'raffle_app': 'drum', 'camera': 'speaker'})
    runs = {src: [tuple(r) for r in lst] for src, lst in (C.get('screen_runs_extra') or {}).items()}
    for tag, part in X.tags.items():
        r = []
        for g in X.SC['sources'][tag]['segments']:
            a, b = g['src_in'], g['src_out']
            sc = g.get('screen_content')
            n = g.get('slide_number')
            if sc in kinds:
                r.append((a, b, kinds[sc], None))
            elif sc in ('black', 'camera_off_placeholder') or (sc or '').startswith('camera_off'):
                r.append((a, b, 'black', None))
            else:
                r.append((a, b, 'slide', n))
        runs[part] = r
    fix = C.get('screen_fixups', []) or []
    b2s = C.get('black_to_slide', {}) or {}
    for part in list(runs):
        if part in X.extra:
            continue
        fixed = []
        for a, b, k, n in runs[part]:
            for fx in fix:
                if fx['src'] == part and fx['from'] <= a < fx['to'] and k == 'slide':
                    n = fx['slide']
            if k == 'black' and part in b2s:
                k, n = 'slide', b2s[part]
            fixed.append((a, b, k, n))
        runs[part] = fixed
    for part in runs:  # merge equal neighbours
        m = []
        for a, b, k, n in runs[part]:
            if m and m[-1][2] == k and m[-1][3] == n and abs(m[-1][1] - a) < 0.2:
                m[-1] = (m[-1][0], b, k, n)
            else:
                m.append((a, b, k, n))
        runs[part] = m
    return runs


def snap_runs_to_chapters(X, RUNS):
    """the slide change nearest to a chapter card (within -5..+5.5 s) is moved onto the card, so the new section's
    slide appears exactly when the card folds away (no 2-4 s of the previous slide after a card)"""
    for part, pts in chapter_points(X).items():
        r = RUNS[part]
        for tt, n, g in pts:
            best = None
            for i in range(1, len(r)):
                bnd = r[i][0]
                if tt - 5.0 <= bnd <= tt + 5.5 and (best is None or abs(bnd - tt) < abs(r[best][0] - tt)):
                    best = i
            if best is not None:
                a0, b0, k0, n0 = r[best - 1]
                a1, b1, k1, n1 = r[best]
                r[best - 1] = (a0, tt, k0, n0)
                r[best] = (tt, b1, k1, n1)
