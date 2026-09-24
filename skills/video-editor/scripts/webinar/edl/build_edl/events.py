"""Accents from highlights, scripted "event scenes" (a raffle drum, a reveal ...) and the wanted name plates.

edl_config.json:
  face_xl_highlights  [["P1", 485.28], ...]   highlights (vision tag, quote start) that get the big face_xl close-up
  events  [{"type": "raffle", ...}]           see raffle() below; every frame is given as SOURCE time and goes
                                              through the output clock, so the event survives any re-cut
  plates  [{"person": "host", "src": "part1", "t": 2.6, "offset_f": 30},
           {"person": "cohost", "src": "part1", "window": [1740, 1800], "speaker": "<name prefix>", "offset_f": 40}]
          person = key of tokens.lower_third.people; a plate rides on a face_xl close-up (G-S9)
"""
from __future__ import annotations


def highlights(X, S):
    FPS, F, ck = X.FPS, S.F, S.ck
    face_xl = {(a, b) for a, b in X.cfg.get('face_xl_highlights', [])}
    for h in X.SC['highlights']:
        part = X.tags.get(h['source'])
        t0 = h.get('quote_start') or h.get('best_in')
        if part is None or t0 is None or not ck.inside(part, t0):
            continue
        typ = h['type']
        f0 = F(part, t0)
        if typ in ('laugh', 'strong_phrase', 'audience_interaction'):
            t1 = h.get('quote_end') or (t0 + 5)
            L = 'face_xl' if (h['source'], t0) in face_xl else 'face'
            d = max(4 * FPS, min((6 if L == 'face_xl' else 8) * FPS, X.fr(t1 - t0) + 20))
            S.accents.append((f0 - 6, f0 - 6 + d, L, (h.get('quote') or '')[:50]))
        elif typ == 'demo_success':
            S.accents.append((f0 - 6, f0 + 5 * FPS, 'face', (h.get('quote') or '')[:50]))
        elif typ == 'reveal' and h.get('screen_content') == 'slide':
            S.accents.append((f0 - 6, f0 + 5 * FPS, 'face', (h.get('quote') or '')[:50]))


def _src_frames(X, S, item, src, y_off):
    """config item with source times -> EDL dict in the SAME key order: t -> from/frame, to_t -> to, rect y += y_off."""
    out = {}
    for k, v in item.items():
        if k == 't':
            out['from'] = S.F(src, v)
        elif k == 'frame_t':
            out['frame'] = S.F(src, v)
        elif k == 'to_t':
            out['to'] = S.F(src, v)
        elif k == 'rect' and y_off:
            out['rect'] = [v[0], v[1] + y_off, v[2], v[3]]
        else:
            out[k] = v
    return out


def raffle(X, S, ev_):
    """Raffle drum (a Zoom share of a random-picker app), the sc4 showcase design on every spin.

    {"type": "raffle", "src": "part2", "y_offset": 119,          content y of the drum clip = drum crop y
     "prizes": [{"t": 4292.0, "refine": [a, b, "regex", shift_s] | null, "name": "<winner as shown>",
                 "prize": "…", "kicker": "…", "extra": "…", "confetti": 110, "row_circle": false}],
     "banner_s": 7, "confetti": {"origin": [960, 470], "spread": 2.6},
     "stars": [{"at": [92, 330], "lead_f": 8}, {"at": [1830, 330], "lead_f": 12}], "stars_s": 4,
     "row_circle": {"rect": [476, 542, 1116, 149], "lead_f": 4, "dur": 14, "hold_s": 6, "width": 8},
     "final": {"t_roll": 4466.7, "feed_at_t": 4470.0, "moves": [...], "marks": [...], "doodles": [...],
               "confetti": [...], "accents": [{"t": a, "to_t": b, "layout": "face_xl", "why": "…"}]},
     "rhythm": {"intro_t": 4258.6, "spins": [4288.8, "prize:1", ..., 4466.7], "after_banner_s": 7.5,
                "before_spin_s": 6.0, "min_s": 8}}
    Winner names are the webinar's data (never in the skill); first names/handles only as the owner approved."""
    FPS, F, ck = X.FPS, S.F, S.ck
    src = ev_['src']
    Y = ev_.get('y_offset', 0)
    prizes = []
    for k, p in enumerate(ev_['prizes']):
        t = p['t']
        if p.get('refine'):
            a, b, rx, shift = p['refine']
            w = X.find_word(src, a, b, rx)
            if w:
                t = w['start'] + shift
        prizes.append(dict(p, t=t))
    drum_feed = [d for d in S.feeds if d.get('_drum')]
    cf_ = ev_.get('confetti', {})
    for k, p in enumerate(prizes):
        t = p['t']
        if not ck.inside(src, t):
            S.report['warnings'].append(f'drum prize {k} at {t} not inside a kept piece')
            continue
        wf = F(src, t)
        S.winners.append({'from': wf + 5, 'to': wf + 5 + ev_.get('banner_s', 7) * FPS, 'kicker': p['kicker'],
                          'name': f"{p['extra']} · {p['name']}", 'prize': p['prize']})
        S.confetti.append({'frame': wf + 3, 'origin': cf_.get('origin', [960, 470]), 'count': p.get('confetti', 70),
                           'spread': cf_.get('spread', 2.6), 'seed': f'c{k}'})
        for st in ev_.get('stars', []):
            S.doodles.append({'type': 'stars', 'from': wf + st['lead_f'], 'to': wf + ev_.get('stars_s', 4) * FPS, 'at': st['at'], 'size': 1.0})
    fin = ev_.get('final')
    if fin and drum_feed and ck.inside(src, fin['t_roll']):
        d = [x for x in drum_feed if x['from'] <= F(src, fin['feed_at_t']) < x['to']]
        if d:
            d = d[0]
            d.setdefault('moves', []).extend([{'frame': F(src, m['t']), 'rect': [m['rect'][0], m['rect'][1] + Y, m['rect'][2], m['rect'][3]], 'dur': m['dur']}
                                              for m in fin.get('moves', [])])
            d.setdefault('marks', []).extend([_src_frames(X, S, m, src, Y) for m in fin.get('marks', [])])
            for dd in fin.get('doodles', []):
                S.doodles.append(_src_frames(X, S, dd, src, 0))
            for c in fin.get('confetti', []):
                S.confetti.append(_src_frames(X, S, c, src, 0))
            for a in fin.get('accents', []):
                S.accents.append((F(src, a['t']), F(src, a['to_t']), a['layout'], a['why']))
    rc = ev_.get('row_circle')
    if rc:
        for k, p in enumerate(prizes):
            if not p.get('row_circle'):
                continue
            t = p['t']
            if not ck.inside(src, t):
                continue
            d = [x for x in drum_feed if x['from'] <= F(src, t) < x['to']]
            if d:
                r = rc['rect']
                d[0].setdefault('marks', []).append({'type': 'circle', 'rect': [r[0], r[1] + Y, r[2], r[3]], 'from': F(src, t) + rc['lead_f'],
                                                     'dur': rc['dur'], 'to': F(src, t) + rc['hold_s'] * FPS, 'width': rc['width']})
    rh = ev_.get('rhythm')
    if rh:
        # the explanation before the first spin and the talk between spins in studio (camera + chat reactions),
        # every spin and its winner banner full-screen; no studio<->full flip shorter than min_s
        spins = [prizes[int(s.split(':')[1])]['t'] if isinstance(s, str) else s for s in rh['spins']]
        first = F(src, rh['intro_t'])
        if first is not None:
            S.accents.append((first, F(src, spins[0]) - 5, 'studio', 'drum intro'))
        for k in range(len(spins) - 1):
            a_t = prizes[k]['t'] + rh.get('after_banner_s', 7.5)
            b_t = spins[k + 1] - rh.get('before_spin_s', 6.0)
            if b_t - a_t >= rh.get('min_s', 8) and ck.inside(src, a_t):
                S.accents.append((F(src, a_t), F(src, b_t), 'studio', 'drum chat'))


def run_events(X, S):
    for e in X.cfg.get('events', []) or []:
        if e['type'] == 'raffle':
            raffle(X, S, e)
        else:
            raise SystemExit(f"edl_config.json events: unknown type {e['type']!r}")


def plates_wanted(X, S):
    """name plates ride on a face_xl close-up: the plate sits on the lower-left of the big camera (classic name
    super), so it never covers slide text (the free-corner search over slides found no corner on dense slides, G-S9)"""
    F = S.F
    want = []
    for p in X.cfg.get('plates', []) or []:
        if 'window' in p:
            a, b = p['window']
            w = next((x for x in X.words_between(p['src'], a, b) if (x.get('speaker') or '').startswith(p['speaker'])), None)
            if w and F(p['src'], w['start']) is not None:
                want.append((p['person'], F(p['src'], w['start']) + p.get('offset_f', 40)))
        else:
            f_ = F(p['src'], p['t'])
            if f_ is not None:
                want.append((p['person'], f_ + p.get('offset_f', 30)))
    S.plate_want = want
    S.plate_acc = [(f_ - 8, f_ + 6 * X.FPS + 12, 'face_xl', f'plate {p_}') for p_, f_ in want]
