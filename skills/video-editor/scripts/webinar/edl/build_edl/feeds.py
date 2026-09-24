"""Main-window feeds: clean slides / live sketch / deck videos / Zoom windows, sketch beats, marks, punch-ins,
board doodles and quote accents (S8 treatments a-d, S10 step 6).

edl_config.json keys used here:
  clips        {"main": {src: "full/clips/p1_main.mp4"}, "cam": {src: ...}, "main_size": [2560, 1608]}
  zoom_feeds   {"demo":    {"prefix": "z", "layout": "full",    "crop": [x, y, w, h], "xfade": 6},
                "drum":    {"prefix": "d", "layout": "full",    "crop": [...], "xfade": 6, "blur": [{"rect": [...]}]},
                "speaker": {"prefix": "c", "layout": "speaker", "crop": [...], "drift": 0.015, "xfade": 8}}
               (crop in main-clip px; the drum crop hides the browser tab strip, G-V5)
  video_dir    "full/video/"
  videos       {slide: [{"src", "t0": number | {"vsync": key} | {"vsync_vis": key, "plus": s}, "file", "dur", "loop",
                         "rect": [x, y, w, h] fractions, "chip": "auto" | false | "force", "end_at": time-spec}]}
  video_studio_slides [7]      the audience votes during these videos: keep the chat column (studio) visible
  video_chip_text "▶ ВИДЕО"
  sketch_slides [..]           slides that get the live sketch (b) on their first long showing
  drift        {"base": 0.022, "step": 0.004, "cap": 0.045}    total push-in cap 4.5 % (G-S4)
  max_punch_ins 30
  cue_fallback {slide: [src, a, b]}   look for cue words in another source (a slide spanning two sources)
  board        {slide: null | {"text": "…", "cue": [src, t], "doodles": [doodle with "from"/"to" = "bf0+8"/"bf1"]}}
  hero_slides  [..], hero_min_gap_s 200
"""
from __future__ import annotations

from .ctx import ev


def nid(S, p):
    S.fid += 1
    return f'{p}{S.fid}'


def put_base(S, f0, f1, layout):
    if f1 > f0:
        S.base.append((f0, f1, layout))


def slide_feed(X, S, n, f0, f1, first):
    """static slide or live sketch feed for slide n over output [f0,f1)"""
    FPS = X.FPS
    dr = X.cfg.get('drift', {})
    base, step, cap = dr.get('base', 0.022), dr.get('step', 0.004), dr.get('cap', 0.045)
    # FeedView drift is linear in time: cap the TOTAL push-in over the feed (a 2-min slide at 2.5 %/10 s would end
    # 30-40 % zoomed and crop the slide text, G-S4)
    d = S.drift_sign * min(base + step * (n % 3), cap * 250 / max(250, f1 - f0))
    S.drift_sign *= -1
    fd = {'id': nid(S, 's'), 'from': f0, 'to': f1, 'kind': 'slide', 'src': f'full/slides/{n:03d}.png', 'cw': 1920,
          'ch': 1080, 'drift': round(d, 4), 'xfade': 6, '_slide': n}
    sm = X.sketch_meta(n) if n in S.sketch_set and n in S.art else None
    if first and sm and (f1 - f0) >= 10 * FPS and f0 - S.sketch_prev_end > 0:
        fd.update({'kind': 'sketch', 'src': f'full/art/{n:03d}.png', 'slideImg': f'full/slides/{n:03d}.png'})
        fd['sketch'] = {'data': f'full/sketch/{n:03d}.json', 'beats': {}, 'durs': {}, 'pen': []}
        S.sketch_prev_end = f1
    S.slide_feed_windows.append((f0, f1, n, fd))
    S.feeds.append(fd)
    return fd


def walk_runs(X, S):
    C = X.cfg
    F = S.F
    clips = C['clips']
    mw, mh = clips.get('main_size', [2560, 1608])
    zf = C['zoom_feeds']
    VID = C.get('video_dir', 'full/video/')
    chip_text = C.get('video_chip_text', '▶ ВИДЕО')
    studio_slides = set(C.get('video_studio_slides', []))
    videos = {int(k): v for k, v in (C.get('videos') or {}).items()}
    first_seen = set()
    for src, runs in S.RUNS.items():
        for a, b, kind, n in runs:
            sp = S.ck.spans(src, a, b)
            if not sp:
                continue
            f0, f1 = sp[0][0], sp[-1][1]
            if kind == 'slide':
                first = n not in first_seen
                first_seen.add(n)
                vids = [v for v in videos.get(n, []) if v['src'] == src and a - 1 <= X.vt(v['t0']) < b]
                fd = slide_feed(X, S, n, f0, f1, first and not vids)
                fd['_src'] = (src, a, b)
                put_base(S, f0, f1, 'audio_only' if src in X.audio_only else 'studio')
                for v in vids:  # deck videos on this slide
                    vt0, vdur, vloop, vr = X.vt(v['t0']), v['dur'], v.get('loop', False), v['rect']
                    v_f0 = F(src, vt0)
                    end_t = min(b, vt0 + vdur) if not vloop else b
                    if v.get('end_at') is not None:
                        end_t = X.vt(v['end_at'])
                    v_f1 = F(src, end_t) if end_t < b else f1
                    if v_f1 is None or v_f1 - v_f0 < 10:
                        continue
                    rect = [round(vr[0] * 1920), round(vr[1] * 1080), round(vr[2] * 1920), round(vr[3] * 1080)]
                    k = 0
                    cur = v_f0
                    seglen = int(round(vdur * X.FPS))
                    # video time runs with the OUTPUT clock inside a span (cuts inside a video run keep it continuous)
                    while cur < v_f1:
                        e = min(v_f1, cur + seglen) if vloop else v_f1
                        S.feeds.append({'id': nid(S, 'v'), 'from': cur, 'to': e, 'kind': 'video', 'src': VID + v['file'],
                                        'cw': 1920, 'ch': 1080, 'srcStart': 0, 'slideImg': f'full/slides/{n:03d}.png',
                                        'videoRect': rect, 'xfade': 6 if k == 0 else 0, '_slide': n})
                        k += 1
                        cur = e
                        if not vloop:
                            break
                    tl_free = 'tl' in ((X.boxes(n) or {}).get('empty_corners') or [])
                    chip = v.get('chip', 'auto')
                    if k and tl_free and chip == 'auto' and not any(abs(c['from'] - (v_f0 + 4)) < 30 for c in S.chips):
                        S.chips.append({'from': v_f0 + 4, 'to': v_f0 + 4 + 50, 'text': chip_text})
                    if n not in studio_slides and src not in X.audio_only:
                        put_base(S, max(f0, v_f0 - 8), min(f1, v_f1 + 12), 'full')
                    elif src in X.audio_only:
                        put_base(S, v_f0 - 8, v_f1 + 12, 'full')
                    if chip == 'force' and tl_free:
                        S.chips.append({'from': v_f0 + 4, 'to': v_f0 + 54, 'text': chip_text})
            elif kind in zf:
                spec = zf[kind]
                for s0, s1, ts in sp:
                    fd = {'id': nid(S, spec.get('prefix', kind[0])), 'from': s0, 'to': s1, 'kind': 'zoom',
                          'src': clips['main'][src], 'cw': mw, 'ch': mh, 'srcStart': X.fr(ts)}
                    for key, val in spec.items():
                        if key not in ('prefix', 'layout'):
                            fd[key] = val
                    if kind == 'drum':
                        fd['_drum'] = True
                    S.feeds.append(fd)
                put_base(S, f0, f1, spec.get('layout', 'full'))
    S.feeds.sort(key=lambda d: (d['from'], d['id']))
    # extend the last feed before each chapter card to card+14 and start the next feed at card+14
    CARD = X.CARD
    for cf, n in S.card_frames:
        for d in [d for d in S.feeds if d['to'] == cf]:
            d['to'] = cf + 14
        for d in [d for d in S.feeds if d['from'] == cf + CARD and d['kind'] != 'video']:
            d['from'] = cf + 14
            if d['kind'] == 'zoom':
                d['srcStart'] = d.get('srcStart', 0) - (CARD - 14)
            d['xfade'] = 0


def beats_marks_punch(X, S):
    """sketch beats on spoken cue words, marks (<= 3) on stressed elements, punch-ins on small circled details."""
    FPS, F, ck = X.FPS, S.F, S.ck
    fallback = {int(k): v for k, v in (X.cfg.get('cue_fallback') or {}).items()}
    max_punch = X.cfg.get('max_punch_ins', 30)
    for f0, f1, n, fd in S.slide_feed_windows:
        bx = X.boxes(n)
        if not bx:
            continue
        src, a, b = fd['_src']
        cue_f = {}
        for e in bx['elements']:
            w = X.find_phrase(src, a - 0.5, b, e.get('cue_words'))
            if w is None and n in fallback and src != fallback[n][0]:
                fs, fa_, fb_ = fallback[n]
                w = X.find_phrase(fs, fa_, fb_, e.get('cue_words'))
                if w is not None and ck.inside(fs, w['start']):
                    cue_f[e['id']] = F(fs, w['start'])
                    continue
            if w is not None and ck.inside(src, w['start']):
                cue_f[e['id']] = F(src, w['start'])
        if fd['kind'] == 'sketch':
            sm = X.sketch_meta(n)
            ids = [e['id'] for e in sm['els']]
            start = fd['from'] + 4
            for a_, b_ in S.card_ranges:  # under a chapter card: start ~20 f before it folds away (slide shows through)
                if a_ <= fd['from'] < b_:
                    start = b_ - 20
            budget_end = fd['from'] + int(0.6 * (fd['to'] - fd['from']))
            n_cued = sum(1 for eid in ids if cue_f.get(eid) is not None and start <= cue_f[eid] <= budget_end)
            slow = n_cued < max(1, len(ids) // 3)  # hardly any cue words: draw at a calm, readable pace
            beats, durs = {}, {}
            t = start
            for eid in ids:
                me = next(e for e in sm['els'] if e['id'] == eid)
                dd = 12 if eid == 'rest' else int(min(56, max(16, 16 + me['ink'] / 2500)))
                if (me.get('kind') or '') == 'title':
                    dd = 24
                cf = cue_f.get(eid)
                bt = t if cf is None or cf < t or cf > budget_end else cf
                if eid == 'rest':
                    bt = t
                if slow and eid != 'rest':
                    dd = int(dd * 1.4)
                beats[eid] = int(bt)
                durs[eid] = dd
                t = int(bt) + (dd + 6 if slow else max(8, dd // 2))
            pens = sorted([e for e in sm['els'] if (e.get('kind') or '') in ('illustration',) and e['id'] != 'rest'], key=lambda e: -e['ink'])[:1]
            fd['sketch'].update({'beats': beats, 'durs': durs, 'pen': [e['id'] for e in pens]})
        marks = []
        for e in bx['elements']:
            mk = e.get('mark')
            if mk in (None, 'none') or e['id'] not in cue_f:
                continue
            cf = cue_f[e['id']]
            if not (fd['from'] + 12 <= cf < fd['to'] - 30):
                continue
            r = X.rect_norm(e.get('mark_box_2d') or e['box_2d'])
            if r[2] < 8 or r[3] < 8:
                continue
            if fd['kind'] == 'sketch':
                cf = max(cf, fd['sketch']['beats'].get(e['id'], cf) + fd['sketch']['durs'].get(e['id'], 0) + 4)
            m = {'type': mk, 'rect': r, 'from': int(cf), 'to': min(fd['to'], int(cf) + 10 * FPS)}
            if mk == 'check':
                m['color'] = '#FFD014'
                m['dur'] = 9
            if mk == 'arrow':
                m['from_side'] = 'left' if r[0] > 400 else 'right'
            marks.append(m)
        marks = sorted(marks, key=lambda m: m['from'])[:3]
        if marks:
            fd['marks'] = marks
        fd['_cues'] = cue_f
        # punch-in on a small circled detail (c): 24 f in, slow creep, 30 f out; the frame edge never cuts an element (G-S3)
        circ = [m for m in marks if m['type'] in ('circle', 'pulse') and m['rect'][2] * m['rect'][3] < 0.1 * 1920 * 1080]
        if circ and fd['to'] - fd['from'] > 20 * FPS and S.punch < max_punch:
            m = circ[0]
            x, y, w, h = m['rect']
            cx, cy = x + w / 2, y + h / 2
            W_ = max(1100, w * 2.4)
            H_ = W_ * 9 / 16
            rx = [cx - W_ / 2, cy - H_ / 2, W_, H_]
            for _ in range(4):  # grow to swallow every element it cuts
                grown = False
                for e in bx['elements']:
                    ex, ey, ew, eh = X.rect_norm(e['box_2d'])
                    ix = min(rx[0] + rx[2], ex + ew) - max(rx[0], ex)
                    iy = min(rx[1] + rx[3], ey + eh) - max(rx[1], ey)
                    if ix > 0 and iy > 0 and (ix < ew - 2 or iy < eh - 2) and ew * eh < 0.35 * 1920 * 1080:
                        nx0, ny0 = min(rx[0], ex - 20), min(rx[1], ey - 20)
                        nx1, ny1 = max(rx[0] + rx[2], ex + ew + 20), max(rx[1] + rx[3], ey + eh + 20)
                        nw = max(nx1 - nx0, (ny1 - ny0) * 16 / 9)
                        rx = [(nx0 + nx1) / 2 - nw / 2, (ny0 + ny1) / 2 - nw * 9 / 32, nw, nw * 9 / 16]
                        grown = True
                if not grown:
                    break
            if rx[2] <= 1500:
                rx[0] = min(max(0, rx[0]), 1920 - rx[2])
                rx[1] = min(max(0, rx[1]), 1080 - rx[3])
                t_in = m['from'] - 8
                fd['moves'] = [{'frame': int(t_in), 'rect': [round(v) for v in rx], 'dur': 24},
                               {'frame': int(t_in + 26), 'rect': [round(rx[0] + rx[2] * 0.02), round(rx[1] + rx[3] * 0.02), round(rx[2] * 0.96), round(rx[3] * 0.96)], 'dur': 110},
                               {'frame': int(t_in + 140), 'rect': [0, 0, 1920, 1080], 'dur': 30}]
                S.punch += 1


def board(X, S):
    """(d) board plan: the slide shrinks, a handwritten note + arrow into the element ride around it."""
    FPS, F, ck = X.FPS, S.F, S.ck
    BOARD = {int(k): v for k, v in (X.cfg.get('board') or {}).items()}
    count = 0
    for f0, f1, n, fd in S.slide_feed_windows:
        if n not in BOARD or not fd.get('_cues') is not None:
            continue
        bx = X.boxes(n)
        src = fd['_src'][0]
        if src in X.audio_only:
            continue
        custom = BOARD[n] or {}
        mn = bx.get('margin_note') if bx else None
        text = custom.get('text') or (mn or {}).get('text')
        if not text:
            continue
        el = (mn or {}).get('element')
        cf = None
        if mn and mn.get('cue_words'):
            w = X.find_phrase(src, fd['_src'][1], fd['_src'][2], mn['cue_words'])
            if w is not None and ck.inside(src, w['start']):
                cf = F(src, w['start'])
        if custom.get('cue'):
            cf = F(custom['cue'][0], custom['cue'][1])
        if cf is None or not (fd['from'] + 2 * FPS <= cf <= fd['to'] - 7 * FPS):
            continue
        bf0, bf1 = cf - 10, min(fd['to'] - 20, cf + 9 * FPS)
        S.accents.append((bf0, bf1, 'board', text[:40]))
        count += 1
        els = {e['id']: e for e in bx['elements']}
        tgt = X.rect_norm(els[el]['box_2d']) if el in els else None
        if tgt:
            cx, cy = tgt[0] + tgt[2] / 2, tgt[1] + tgt[3] / 2
            if custom.get('doodles'):
                names = {'bf0': bf0, 'bf1': bf1}
                for d in custom['doodles']:
                    S.doodles.append({k: (ev(v, names) if k in ('from', 'to') else v) for k, v in d.items()})
                continue
            if cy >= 540:  # label in the bottom margin, arrow up into the element's bottom edge
                S.doodles.append({'type': 'label', 'from': bf0 + 8, 'to': bf1, 'at': [262, 790], 'text': text, 'size': 40, 'rotate': -1.5})
                if tgt[1] + tgt[3] > 760:
                    S.doodles.append({'type': 'arrow', 'from': bf0 + 16, 'to': bf1, 'at': [262 + min(700, 24 * len(text)), 812],
                                      'to_content': [int(cx), int(tgt[1] + tgt[3] + 6)], 'bend': 14})
            else:  # label in the top margin, arrow down into the element's top edge
                S.doodles.append({'type': 'label', 'from': bf0 + 8, 'to': bf1, 'at': [262, 30], 'text': text, 'size': 40, 'rotate': -1.5, 'color': '#FFD014'})
                if tgt[1] < 300:
                    S.doodles.append({'type': 'arrow', 'from': bf0 + 16, 'to': bf1, 'at': [262 + min(700, 24 * len(text)), 70],
                                      'to_content': [int(cx), int(max(4, tgt[1] - 6))], 'bend': -14})
            S.doodles.append({'type': 'stars', 'from': bf0 + 24, 'to': bf1, 'at': [60, 180 if cy >= 540 else 700], 'size': 0.8})
    S.report['boards'] = count
    S.report['punch_ins'] = S.punch


def heroes(X, S):
    """quote accents: key phrases NOT written on the slide, >= hero_min_gap_s apart (G-S8)."""
    FPS, F, ck = X.FPS, S.F, S.ck
    pick = set(X.cfg.get('hero_slides', []))
    gap = X.cfg.get('hero_min_gap_s', 200)
    hero_f = []
    out = []
    for f0, f1, n, fd in S.slide_feed_windows:
        if n not in pick:
            continue
        kp = (X.boxes(n) or {}).get('key_phrase')
        if not kp or not kp.get('text') or len(kp['text']) > 60:
            continue
        src, a, b = fd['_src']
        w = X.find_phrase(src, a, b, kp.get('start_words'))
        if w is None or not ck.inside(src, w['start']):
            continue
        hf0 = F(src, w['start'])
        nw = len(kp['text'].split())
        ws = [x for x in X.words_between(src, w['start'], w['start'] + 12)][:nw]
        hf1 = F(src, ws[-1]['end']) + 12 if ws else hf0 + 75
        hf1 = max(hf0 + 50, min(hf0 + 110, hf1))
        if hero_f and hf0 - hero_f[-1] < gap * FPS:
            continue
        em = kp.get('em') or ''
        out.append({'from': hf0, 'to': hf1, 'text': kp['text'].strip(' .'), 'em': em if em and em in kp['text'] else None})
        hero_f.append(hf0)
    S.heroes = [{k: v for k, v in h.items() if v is not None} for h in out]
