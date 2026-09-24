"""EDL builder orchestration (architecture E, 25 fps, frame-exact): runs every module in the order of the reference
run and writes the job's edl/ outputs.

  edl/edl.json            master EDL (templates/remotion-program/src/program/types.ts contract + pieces, teaser,
                          cards, cuts, flags, assets, render notes)
  edl/chapters.json       [{title, final_start_s, card_n, time}]  (-> RuTube chapters, PDF timecodes)
  edl/subtitles.srt       final timeline
  edl/audio_plan.json     voice pieces + music cues for audio/mix_full.py
  edl/final_duration.txt, edl/report_build.json, edl/owner_review.json (decisions left to the owner, NOT applied)

Post-passes (on by default, --raw switches them off to compare with a pre-fix reference):
  sync_cams         every camera frame shows the same source time as the voice piece under it. Without it the
                    camera of the first speaker run after every chapter card started at the CARD start with
                    srcStart = piece.t0, i.e. 91 f (3.64 s) ahead of the voice for the whole piece (G-E6).
  fill_sketch_gaps  a live sketch feed never shows an empty canvas: if its first beat is > 50 f after the feed
                    start, the earliest element(s) start at feed.from + 6 (G-E5).
"""
from __future__ import annotations

import json
import os
import re
import sys

from . import captions, chat, clock, events, feeds, layouts, polls
from .ctx import Ctx, ev, tc


class State:
    """Mutable state of one build (the reference builder kept it in closures of one 1500-line function)."""

    def __init__(self):
        self.report = {'warnings': [], 'flags': []}
        self.fid = 0
        self.punch = 0
        self.drift_sign = 1
        self.sketch_prev_end = -10**9
        self.feeds, self.base, self.doodles, self.chips, self.tags, self.heroes = [], [], [], [], [], []
        self.accents, self.winners, self.confetti = [], [], []
        self.slide_feed_windows = []
        self.ev = ev

    def names(self):
        n = {'t_end': self.t_end, 'b0': self.pieces_out[0]['f0'] if self.pieces_out else 0,
             'broadcast_end': self.broadcast_end, 'dur': self.dur}
        for i, f in enumerate(self.teaser_from):
            n[f'tf{i}'] = f
            if i < 3:
                n[('fa', 'fb', 'fc')[i]] = f
        return n


def sync_cams(X, edl):
    """G-E6 fix (reference: edl/fix_cam_sync.py of the reference run, applied 24.09 20:36)."""
    FPS = X.FPS
    part_of = {f: s for s, f in X.cfg['clips']['cam'].items()}
    dstart = {}
    for s, c in ((X.cfg.get('cam2') or {}).get('clips') or {}).items():
        part_of[c['file']] = s
        dstart[c['file']] = c['start']
    pieces = edl['pieces']

    def piece_for(src_key, f):
        for p in pieces:
            if p['src'] == src_key and p['from'] <= f < p['to']:
                return p
        return None

    fixed = []
    for c in edl['cams']:
        key = part_of.get(c['src'])
        if key is None:
            continue
        lo, hi = c['from'], c['to']
        mid = None
        for f in range(lo, hi, 5):  # the part of the entry that lies inside a piece (skip the card overlap)
            p = piece_for(key, f)
            if p:
                mid = (f, p)
                if f - lo > 100:
                    break
        if not mid:
            continue
        f, p = mid
        want = round((p['t0'] + (f - p['from']) / FPS - dstart.get(c['src'], 0.0)) * FPS) - (f - c['from'])
        d = c['srcStart'] - want
        if d != 0:
            fixed.append({'src': c['src'], 'from': c['from'], 'to': c['to'], 'old': c['srcStart'], 'new': want, 'ahead_f': d})
            c['srcStart'] = want
    return fixed


def fill_sketch_gaps(edl, min_gap=50, lead=6):
    """G-E5 fix (reference: edl/fix_sketch_gaps.py, applied 24.09 20:00)."""
    out = []
    for f in edl['feeds']:
        if f['kind'] != 'sketch' or not f.get('sketch', {}).get('beats'):
            continue
        b = f['sketch']['beats']
        first = min(b.values())
        if first - f['from'] <= min_gap:
            continue
        keys = [k for k, v in b.items() if v == first]
        for k in keys:
            b[k] = f['from'] + lead
        out.append({'feed': f['id'], 'gap_f': first - f['from'], 'elements': keys})
    return out


def main(raw=False):
    X = Ctx()
    S = State()
    C = X.cfg
    FPS, CARD = X.FPS, X.CARD
    CUTS = clock.cuts(X)
    S.RUNS = clock.screen_runs(X)
    clock.snap_runs_to_chapters(X, S.RUNS)
    S.sketch_set = set(C.get('sketch_slides', []))
    S.art = X.art_set()
    seq = clock.build_pieces(X, CUTS)
    S.ck = ck = clock.Clock(FPS)

    # ---------------- teaser («best of» cold open) on its own clock
    T = C.get('teaser') or {}
    S.teaser_cfg = T
    S.teaser = [tuple(p) for p in T.get('pieces', [])]
    S.teaser_layouts = T.get('layouts', [])
    S.intro_layouts = T.get('intro_layouts', [{'frame': 0, 'layout': 'intro_hidden'}, {'frame': 194, 'layout': 'studio', 'morph': 18}])
    S.tclk = clock.Clock(FPS)
    f = T.get('start_frame', 200)
    S.teaser_from = []
    for src, a, b in S.teaser:
        S.teaser_from.append(f)
        f = S.tclk.add(src, a, b, f)
    S.t_end = f + T.get('tail', 22)
    f = S.t_end
    S.card_frames, S.pieces_out = [], []
    for it in seq:
        if 'chapter' in it:
            S.card_frames.append((f, it['chapter']))
            f += CARD
        else:
            f0 = f
            f = ck.add(it['src'], it['t0'], it['t1'], f)
            S.pieces_out.append({'src': it['src'], 't0': it['t0'], 't1': ck.segs[-1][2], 'f0': f0, 'f1': f})
    S.broadcast_end = f
    outro_from = S.broadcast_end  # hard cut on the last room tone; the outro fades itself to black
    S.dur = dur = outro_from + X.TOK['outro']['duration_s'] * FPS
    S.F = F = lambda src, t, clamp=True: ck.f(src, t, clamp)  # noqa: E731
    S.card_ranges = [(a, a + CARD) for a, _ in S.card_frames]

    words = captions.build_words(X, S)
    cues, capwords = captions.build_cues(X, S, words)

    feeds.walk_runs(X, S)
    feeds.beats_marks_punch(X, S)
    events.highlights(X, S)
    feeds.board(X, S)
    feeds.heroes(X, S)
    events.run_events(X, S)
    events.plates_wanted(X, S)
    layouts.layout_keys(X, S)
    layouts.cams(X, S)
    chat.build_chat(X, S)
    polls.build_polls(X, S)

    # ---------------- lower thirds (plates on accepted face_xl close-ups; fallback: a free corner of the slide)
    LAY = X.LAY
    lay = S.lay

    def plate_free(frame, h=135):
        L = str(lay[min(dur - 1, frame)])
        if L not in LAY or not LAY[L].get('lower_third_anchor'):
            return False
        if L == 'face_xl':  # anchor is on the big camera (lower-left), not on the slide
            return True
        act = [d for d in S.feeds if d['from'] <= frame < d['to']]
        if not act:
            return False
        n = act[-1].get('_slide')
        if n is None:
            return False
        bx = X.boxes(n)
        if not bx:
            return False
        mx, my, mw, mh = LAY[L]['main']
        k = mw / 1920
        ax, ay = LAY[L]['lower_third_anchor']
        x0, y0, x1, y1 = (ax - mx) / k, (ay - h - my) / k, (ax + 470 - mx) / k, (ay - my) / k
        parea = (x1 - x0) * (y1 - y0)
        for e in bx['elements']:
            ex, ey, ew, eh = X.rect_norm(e['box_2d'])
            ix = min(x1, ex + ew) - max(x0, ex)
            iy = min(y1, ey + eh) - max(y0, ey)
            if ix > 0 and iy > 0:
                # text is never covered; a corner of a drawing may be (<= 30 % of the plate)
                if (e.get('kind') or '') != 'illustration' or ix * iy > 0.3 * parea:
                    return False
        return True

    def place_plate(person, f_want, search_s=60):
        for d_ in range(0, search_s * FPS, 12):
            f_ = f_want + d_
            if all(plate_free(f_ + k_) for k_ in (0, 60, 124)):
                return {'person': person, 'from': f_, 'to': f_ + 5 * FPS}
        S.report['warnings'].append(f'no free corner for the {person} plate near {tc(f_want / FPS)} — plate skipped')
        return None

    lts = []
    for p_, f_ in S.plate_want:
        acc_ = next((a for a in S.accepted if a[3] == f'plate {p_}' and a[0] <= f_ < a[1]), None)
        if acc_:
            lts.append({'person': p_, 'from': acc_[0] + 18, 'to': min(acc_[1] - 4, acc_[0] + 18 + 5 * FPS)})
        else:
            lts.append(place_plate(p_, f_, 240))
    lts = [x for x in lts if x]
    names = S.names()
    for tg in C.get('tags', []) or []:
        if 'after_video' in tg:
            vv = [d for d in S.feeds if d['kind'] == 'video' and d['src'].endswith(tg['after_video'])]
            if vv:
                a = vv[0]['to'] + tg.get('offset_f', 20)
                S.tags.append({'from': a, 'to': a + int(tg.get('dur_s', 5) * FPS), 'text': tg['text']})
            continue
        a = ev(tg['from'], names)
        b = ev(tg['to'], names) if 'to' in tg else a + int(tg.get('dur_s', 5) * FPS)
        S.tags.append({'from': a, 'to': b, 'text': tg['text']})

    # ---------------- teaser feeds, marks, doodles; intro art
    tfeeds = []
    for spec in T.get('feeds', []):
        n = spec['slide']
        fd = {'id': spec['id'], 'from': ev(spec['from'], names), 'to': ev(spec['to'], names), 'kind': spec['kind']}
        if spec['kind'] == 'sketch':
            fd.update({'src': f'full/art/{n:03d}.png', 'cw': 1920, 'ch': 1080, 'slideImg': f'full/slides/{n:03d}.png',
                       'sketch': {'data': f'full/sketch/{n:03d}.json', 'beats': {}, 'durs': {}, 'pen': [], 'settle': spec.get('settle', 10**6)}})
            sm = X.sketch_meta(n)
            bs = spec.get('beats')
            if sm and bs:
                ids = [e['id'] for e in sm['els']]
                bt, du = {}, {}
                t = bs.get('start', 188)
                for i, eid in enumerate(ids):
                    bt[eid] = t
                    du[eid] = bs.get('first_dur', 14) if i == 0 else bs.get('dur', 26)
                    t += bs.get('step', 12)
                fd['sketch'].update({'beats': bt, 'durs': du, 'pen': [ids[min(bs.get('pen_index', 2), len(ids) - 1)]]})
        else:
            fd.update({'src': f'full/slides/{n:03d}.png', 'cw': 1920, 'ch': 1080})
        for k in ('drift', 'xfade'):
            if k in spec:
                fd[k] = spec[k]
        ul = spec.get('underline')
        bxn = X.boxes(n)
        if ul and bxn:
            um = next((e for e in bxn['elements'] if e.get('mark') == 'underline'), None)
            if um:
                fd['marks'] = [{'type': 'underline', 'rect': X.rect_norm(um.get('mark_box_2d') or um['box_2d']),
                                'from': S.tclk.f(ul['t'][0], ul['t'][1]), 'dur': ul.get('dur', 14)}]
        tfeeds.append(fd)
    for d in T.get('doodles', []):
        S.doodles.append({k: (ev(v, names) if k in ('from', 'to') else v) for k, v in d.items()})
    IC = C.get('intro') or {}
    intro = {'titleFrom': IC.get('titleFrom', 60), 'titleTo': IC.get('titleTo', 206)}
    sm3 = X.sketch_meta(IC['art_slide']) if IC.get('art_slide') else None
    if sm3:
        big = sorted([e for e in sm3['els'] if e['id'] != 'rest'], key=lambda e: -e['ink'])[:2]
        parts = []
        for i, pspec in enumerate(IC.get('art_parts', [])):
            ids = [big[i]['id']] if i < len(big) else [big[0]['id']]
            parts.append({'ids': ids, **pspec})
        intro['art'] = {'data': f"full/sketch/{IC['art_slide']:03d}.json", 'parts': parts}
    S.feeds = tfeeds + S.feeds
    chat.teaser_chat(X, S)

    # ---------------- chapters
    chapters = []
    chap_json = [{'title': T.get('chapter_title', 'Лучшее из эфира'), 'final_start_s': 0.0}]
    chcfg = {c['n']: c for c in C['chapters']}
    for cf, n in S.card_frames:
        c = chcfg[n]
        lines, note, art_slide = c['lines'], c.get('note'), c.get('art_slide')
        fromL = lay[cf - 1] if cf > 0 else 'studio'
        toL = lay[min(dur - 1, cf + CARD)]
        if fromL in ('intro_hidden',):
            fromL = 'studio'
        spec = {'from': cf, 'n': n, 'time': tc(cf / FPS), 'lines': lines, 'theme': 'dark', 'fromLayout': str(fromL), 'toLayout': str(toL)}
        if note:
            spec['note'] = note
        if art_slide:
            smm = X.sketch_meta(art_slide)
            if smm:
                ill = sorted([e for e in smm['els'] if e['id'] != 'rest' and (e.get('kind') in ('illustration', 'item', 'number', None))], key=lambda e: -e['ink'])
                if c.get('art_ids'):
                    ill = [e for e in smm['els'] if e['id'] in c['art_ids']] or ill
                if ill:
                    spec['art'] = {'data': f'full/sketch/{art_slide:03d}.json', 'ids': [ill[0]['id']], 'speed': 0.8}
                spec['theme'] = 'paper' if smm['theme'] == 'paper' else 'dark'
        chapters.append(spec)
        chap_json.append({'title': ' '.join(lines).replace('  ', ' '), 'final_start_s': round(cf / FPS, 2), 'card_n': n, 'time': tc(cf / FPS)})

    # ---------------- flags for the owner (content rules, spoken names) - never applied automatically
    for p in X.parts:
        wf = X.words_json(p)
        for cfl in wf.get('content_flags', []):
            t = cfl['t']
            if ck.inside(p, t):
                S.report['flags'].append({'final_s': round(F(p, t) / FPS, 2), 'final_tc': tc(F(p, t) / FPS), 'src': p, 't': t,
                                          'note': cfl['note'], 'context': cfl.get('context', '')[:140]})
    for sf in C.get('spoken_flags', []) or []:
        rx = re.compile(sf['regex'])
        for p in list(X.extra) + list(X.parts):
            for w in X.W[p]:
                lw = w['punctuated_word'].lower()
                if rx.search(lw) and ck.inside(p, w['start']):
                    ctx = ' '.join(x['punctuated_word'] for x in X.words_between(p, w['start'] - 6, w['start'] + 6))
                    S.report['flags'].append({'final_s': round(F(p, w['start']) / FPS, 2), 'final_tc': tc(F(p, w['start']) / FPS), 'src': p,
                                              't': w['start'], 'note': sf['note'], 'context': ctx[:160]})

    # ---------------- assemble
    for d in S.feeds:
        for k in [k for k in d if k.startswith('_')]:
            d.pop(k)
    S.feeds.sort(key=lambda d: d['from'])
    tf = S.teaser_from
    edl = {
        'id': C.get('edl_id', 'full'),
        'durationInFrames': int(dur),
        'fps': FPS,
        'layouts': S.layouts,
        'feeds': S.feeds,
        'cams': sorted(S.cams, key=lambda c: c['from']),
        'words': capwords,
        'cues': cues,
        'heroes': S.heroes,
        'chat': S.chat_items,
        'polls': S.polls,
        'reactions': S.reactions,
        'lowerThirds': lts,
        'doodles': sorted(S.doodles, key=lambda d: d['from']),
        'chapters': chapters,
        'winners': S.winners,
        'confetti': S.confetti,
        'chips': S.chips,
        'tags': S.tags,
        'intro': intro,
        'outro': {'from': outro_from},
        'fadeOut': 0,
        'pieces': [{'src': p['src'], 't0': round(p['t0'], 3), 't1': round(p['t1'], 3), 'from': p['f0'], 'to': p['f1']} for p in S.pieces_out],
        'teaser': [{'src': s, 't0': a, 't1': round(a + X.fr(b - a) / FPS, 3), 'from': f0, 'to': f0 + X.fr(b - a)} for (s, a, b), f0 in zip(S.teaser, tf)],
        'cards': [{'from': a, 'to': a + CARD, 'n': n} for a, n in S.card_frames],
        'cuts': {k: [[round(x, 3), round(y, 3)] for x, y in v] for k, v in CUTS.items()},
        'cut_notes': clock.cut_notes(X),
        'flags': S.report['flags'],
    }
    assets = dict(C.get('assets') or {})
    assets.setdefault('public_dir', str(X.PUB).replace('\\', '/'))
    edl['assets'] = {'public_dir': assets.pop('public_dir'), **assets}
    edl['render'] = C.get('render_notes') or {
        'chunks': 'python scripts/webinar/edl/split_chunks.py --job job.json -> edl/chunks/full_NNN.json + index.json',
        'command': 'templates/remotion-program: render_worker.mjs (one node process per worker, lock-file chunk claim, resumable)',
        'tokens_note': 'style/tokens.json is baked into the JS bundle: re-bundle after any tokens/src change (G-R2)'}
    post = {}
    if not raw:
        post['fill_sketch_gaps'] = fill_sketch_gaps(edl)
        post['sync_cams'] = sync_cams(X, edl)
    S.report['post_passes'] = post if not raw else 'skipped (--raw)'
    return X, S, edl, chap_json, outro_from


def write_outputs(X, S, edl, chap_json):
    FPS, CARD, OUT = X.FPS, X.CARD, X.OUT
    C = X.cfg

    def dump(name, obj, compact=False):
        p = OUT / name
        tmp = p.with_name(p.name + '.tmp')
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            if compact:
                json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
            else:
                json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)

    dump('edl.json', edl, compact=True)
    dump('chapters.json', chap_json)
    # audio plan: voice pieces (teaser + broadcast), music under the teaser, every chapter card and the outro
    M = C.get('music') or {}
    music_src = X.J.rel(M.get('src') or X.J.get('audio.music_bed', 'audio/music/bed.wav'))
    gain = C.get('gain_db', {})
    voice = []
    for (s, a, b), f0 in zip(S.teaser, S.teaser_from):
        voice.append({'at_s': round(f0 / FPS, 3), 'src': X.src_audio(s), 'src_key': s, 't0': a, 't1': round(a + X.fr(b - a) / FPS, 3), 'gain_db': gain.get(s, 0.0)})
    for p in S.pieces_out:
        voice.append({'at_s': round(p['f0'] / FPS, 3), 'src': X.src_audio(p['src']), 'src_key': p['src'], 't0': round(p['t0'], 3),
                      't1': round(p['t1'], 3), 'gain_db': gain.get(p['src'], 0.0)})
    mt, mc, mo = M.get('teaser', {}), M.get('cards', {}), M.get('outro', {})
    fa = S.teaser_from[0] if S.teaser_from else 0
    music = [{'src': music_src, 'at_s': 0.0, 'from_s': mt.get('from_s', 7.8), 'to_s': round(S.t_end / FPS, 3),
              'alone_until_s': round(fa / FPS - 0.3, 3), 'note': mt.get('note', 'intro teaser')}]
    for cf, n in S.card_frames:
        music.append({'src': music_src, 'at_s': round(cf / FPS - mc.get('pre_s', 1.2), 3),
                      'from_s': mc.get('from_s', 8.0) + (n % mc.get('cycle', 4)) * mc.get('step_s', 15.8),
                      'to_s': round((cf + CARD) / FPS + mc.get('post_s', 0.8), 3), 'alone_from_s': round(cf / FPS, 3),
                      'alone_until_s': round((cf + CARD) / FPS, 3), 'note': f'chapter card {n}'})
    music.append({'src': music_src, 'at_s': round(S.broadcast_end / FPS - mo.get('pre_s', 0.5), 3), 'from_s': mo.get('from_s', 31.0),
                  'to_s': round(edl['durationInFrames'] / FPS, 3), 'alone_from_s': round(S.broadcast_end / FPS, 3), 'note': mo.get('note', 'outro')})
    gains = '/'.join(f'{gain[p]:+.1f}' for p in X.parts if p in gain)
    audio = {'fps': FPS, 'dur_s': edl['durationInFrames'] / FPS, 'program_lufs': X.J.get('audio.target_lufs', -16.0),
             'true_peak_dbtp': X.J.get('audio.true_peak', -1.5), 'crossfade_ms': 20, 'voice': voice, 'music': music,
             'rules': C.get('audio_rules_note') or ('voice pieces butt-joined with 20 ms crossfades; teaser pieces and chapter-card gaps are '
                                                    f'silent in the voice track (music only); part gains static {gains} dB; final two-pass '
                                                    'loudnorm -16 LUFS / -1.5 dBTP (audio/mix_full.py)')}
    dump('audio_plan.json', audio)

    def srt_t(frames):
        ms = int(round(frames / FPS * 1000))
        h, r = divmod(ms, 3600000)
        m, r = divmod(r, 60000)
        s, ms = divmod(r, 1000)
        return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

    lines = []
    wds = edl['words']
    for i, c in enumerate(edl['cues'], 1):
        txt = '\n'.join(' '.join(wds[j]['w'] for j in ln) for ln in c['lines'])
        lines.append(f"{i}\n{srt_t(c['start'])} --> {srt_t(c['end'])}\n{txt}\n")
    (OUT / 'subtitles.srt').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    d = edl['durationInFrames']
    (OUT / 'final_duration.txt').write_text(f'{d} frames @{FPS} fps = {d / FPS:.2f} s = {tc(d / FPS)}\n', encoding='utf-8', newline='\n')
    dump('report_build.json', S.report)

    def at(src, t):
        for p in S.pieces_out:
            if p['src'] == src and p['t0'] <= t < p['t1']:
                return (p['f0'] + int(round((t - p['t0']) * FPS))) / FPS
        return None

    R = C.get('owner_review') or {}
    cuts = []
    for oc in R.get('optional_cuts', []):
        a, b = at(oc['src'], oc['t0']), at(oc['src'], oc['t1'])
        cuts.append({'what': oc['what'], 'src': oc['src'], 't0': oc['t0'], 't1': oc['t1'],
                     'final_from': tc(a) if a is not None else None, 'final_to': tc(b) if b is not None else None,
                     'len_s': round(oc['t1'] - oc['t0'], 1)})
    review = {'note': 'Nothing below is applied to the cut; each item has final-timeline timecodes so it can be cut/replaced in one edit.',
              'optional_cuts': cuts, 'spoken_flags': S.report['flags'], 'unconfirmed': R.get('unconfirmed', [])}
    dump('owner_review.json', review)
    E = edl
    print('EDL', d, 'frames', tc(d / FPS), 'feeds', len(E['feeds']), 'cues', len(E['cues']), 'chat', len(E['chat']), 'polls', len(E['polls']),
          'reactions', len(E['reactions']), 'chapters', len(E['chapters']), 'heroes', len(E['heroes']), 'doodles', len(E['doodles']))
    print('accents', S.report.get('accents'), 'boards', S.report.get('boards'), 'warnings', S.report['warnings'][:10], 'flags', len(S.report['flags']))
    post = S.report.get('post_passes')
    if isinstance(post, dict):
        print('post-passes: sketch gaps filled', len(post['fill_sketch_gaps']), '| cams re-synced', len(post['sync_cams']))


def cli(argv=None):
    raw = '--raw' in sys.argv
    X, S, edl, chap_json, _ = main(raw=raw)
    write_outputs(X, S, edl, chap_json)
