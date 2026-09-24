"""Plan (layout) keyframes and cameras (S10 steps 6-8).

Plans come from the base (slide -> studio, demo/drum/video -> full, camera share -> speaker, recorder-only ->
audio_only) plus accents (face / face_xl / board from highlights, events, plates). Accepted accents keep 60 f apart
and 30 f off chapter cards; islands shorter than min_hold_s fall into their neighbour (face_xl excepted).

edl_config.json:
  min_hold_s 3                      shortest plan island
  cam2   {"speaker_prefix": "<co-host name prefix>", "clips": {src: {"file": "full/clips/p1_cam2.mp4",
          "start": 1700.0, "live": [1700.0, null]}}}   the second camera is used only where it is live
"""
from __future__ import annotations

import numpy as np


def layout_keys(X, S):
    FPS, dur = X.FPS, S.dur
    lay = np.array(['studio'] * dur, dtype=object)
    for f0, f1, L in sorted(S.base, key=lambda x: (x[0], 0 if x[2] in ('studio', 'audio_only') else 1)):
        lay[max(0, f0):min(dur, f1)] = L
    accepted = []
    for f0, f1, L, why in S.plate_acc + sorted(S.accents):
        f0, f1 = max(0, int(f0)), min(dur, int(f1))
        seg = set(lay[f0:f1])
        if L in ('face', 'face_xl', 'board'):
            if not seg <= {'studio'} and not (L == 'face' and seg <= {'full'}) and not (L == 'face_xl' and seg <= {'full', 'studio'}):
                continue
            if any(a < f1 + 60 and f0 < b + 60 for a, b, *_ in accepted):
                continue
            if any(a - 30 < f1 and f0 < b + 30 for a, b in S.card_ranges):
                continue
        lay[f0:f1] = L
        accepted.append((f0, f1, L, why))
    S.report['accents'] = {k: sum(1 for a in accepted if a[2] == k) for k in ('face', 'face_xl', 'board', 'studio')}
    S.accepted = accepted
    # teaser plans
    names = S.names()
    for a, b, L in S.teaser_layouts:
        lay[int(S.ev(a, names)):int(S.ev(b, names))] = L
    for a, b in S.card_ranges:
        lay[a:b] = lay[b] if b < dur else lay[a - 1]
    lay[S.broadcast_end:dur] = lay[S.broadcast_end - 1]
    keys = []
    i = 0
    while i < dur:
        j = i
        while j < dur and lay[j] == lay[i]:
            j += 1
        keys.append([i, j, lay[i]])
        i = j
    hold = X.cfg.get('min_hold_s', 3) * FPS
    changed = True
    while changed:
        changed = False
        for k in range(1, len(keys) - 1):
            a, b, L = keys[k]
            if b - a < hold and L not in ('face_xl',):
                keys[k][2] = keys[k - 1][2]
                changed = True
        merged = []
        for kk in keys:
            if merged and merged[-1][2] == kk[2]:
                merged[-1][1] = kk[1]
            else:
                merged.append(kk)
        keys = merged
    layouts = [dict(x) for x in S.intro_layouts]
    first_free = S.teaser_cfg.get('layouts_from', 200)
    for a, b, L in keys:
        if a < first_free:
            continue
        m = 16 if 'face' in L else 15
        layouts.append({'frame': int(a), 'layout': L, 'morph': m})
    fb = names['fb']
    layouts[2]['frame'] = fb if layouts[2]['frame'] < fb else layouts[2]['frame']
    S.lay = lay
    S.layouts = layouts


def cams(X, S):
    """host camera; the co-host camera by speaker (1 s steps, runs < 2.5 s merged), split at every cut and card."""
    F = S.F
    C = X.cfg
    camf = C['clips']['cam']
    cam2 = C.get('cam2') or {}
    out = []
    for (src, a, b), f0 in zip(S.teaser, S.teaser_from):  # teaser cams
        out.append({'src': camf[src], 'srcStart': X.fr(a), 'from': f0, 'to': f0 + X.fr(b - a)})
    out[-1]['to'] = S.t_end

    def speaker_at(src, t):
        ws = X.words_between(src, t - 3, t + 3)
        if not ws:
            return None
        return min(ws, key=lambda w: abs(w['start'] - t)).get('speaker')

    for p in S.pieces_out:
        src = p['src']
        if src in X.audio_only:
            continue
        t = p['t0']
        cur_spk, run0 = None, p['t0']
        runs = []
        while t < p['t1']:
            s = speaker_at(src, t) or cur_spk
            if s != cur_spk:
                if cur_spk is not None:
                    runs.append((run0, t, cur_spk))
                cur_spk, run0 = s, t
            t += 1.0
        runs.append((run0, p['t1'], cur_spk))
        mr = []
        for r in runs:
            if mr and (r[1] - r[0] < 2.5 or r[2] == mr[-1][2]):
                mr[-1] = (mr[-1][0], r[1], mr[-1][2])
            else:
                mr.append(r)
        c2 = (cam2.get('clips') or {}).get(src)
        for a, b, s in mr:
            f0, f1 = F(src, a), (F(src, b) if b < p['t1'] else p['f1'])
            if f1 is None or f1 <= f0:
                continue
            co = bool(s and cam2 and s.startswith(cam2['speaker_prefix']))
            if co and c2 and a >= c2['live'][0] and (c2['live'][1] is None or b <= c2['live'][1]):
                out.append({'src': c2['file'], 'srcStart': X.fr(a - c2['start']), 'from': f0, 'to': f1})
            else:
                out.append({'src': camf[src], 'srcStart': X.fr(a), 'from': f0, 'to': f1})
    for cf, n in S.card_frames:  # camera continues under the first 14 frames of a card
        for c in out:
            if c['to'] == cf:
                c['to'] = cf + 14
    S.cams = out
