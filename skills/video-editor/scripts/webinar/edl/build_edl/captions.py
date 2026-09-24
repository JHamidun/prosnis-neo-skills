"""Words on the output clock -> caption cues (<= 2 lines, balanced), key-word pill on ~35-40 % of cues (S10 step 5).

Rules (style.md §6): a cue breaks on a pause > 8 f, > 2 lines, > 5.6 s, a sentence end after 24+ characters,
a speaker change, a cut between two words, a chapter card; cues never overlap; fillers and drop_words (private
surnames) never reach the subtitles. edl_config.json: pill_keyterms (stems that always get the pill), drop_words.
"""
from __future__ import annotations

import re

from .ctx import FILLER


def add_words(X, clock, src, a, b, drop=()):
    out = []
    lo = X.range_start.get(src)
    for w in X.words_between(src, a, b):
        txt = w['punctuated_word']
        if FILLER.match(txt) or txt.lower().strip('.,!?«»') in drop:
            continue
        if lo is not None and w['start'] < lo:
            continue
        if not clock.inside(src, w['start']):
            continue
        s = clock.f(src, w['start'], False)
        e = clock.f(src, min(w['end'], w['start'] + 2.5), True)
        if s is None:
            continue
        if e is None or e <= s:
            e = s + 3
        out.append({'w': txt, 's': s, 'e': max(e, s + 3), 'ts': w['start'], 'te': w['end'], 'src': src, 'spk': w.get('speaker')})
    return out


def build_words(X, S):
    tw = []
    for (src, a, b) in S.teaser:
        tw += add_words(X, S.tclk, src, a, b)
    bw = []
    for p in S.pieces_out:
        bw += add_words(X, S.ck, p['src'], p['t0'], p['t1'] - 1e-3, drop=X.drop_words)
    seen = set()
    allw = []
    for w in tw + bw:  # dedupe (pieces share boundaries)
        k = (w['s'], w['w'])
        if k in seen:
            continue
        seen.add(k)
        allw.append(w)
    allw.sort(key=lambda w: w['s'])
    return allw


def build_cues(X, S, words):
    FPS = X.FPS
    maxc = X.TOK['captions']['max_chars_per_line']
    cues = []
    cur = []

    def flush():
        if not cur:
            return
        lines, line = [], []
        for i in cur:
            cand = ' '.join(words[j]['w'] for j in line + [i])
            if len(cand) > maxc and line:
                lines.append(line)
                line = [i]
            else:
                line.append(i)
        if line:
            lines.append(line)
        if len(lines) == 2:
            flat = lines[0] + lines[1]
            best = None
            for k in range(1, len(flat)):
                a = ' '.join(words[j]['w'] for j in flat[:k])
                b = ' '.join(words[j]['w'] for j in flat[k:])
                if max(len(a), len(b)) <= maxc:
                    sc = abs(len(a) - len(b))
                    if best is None or sc < best[0]:
                        best = (sc, k)
            if best:
                lines = [flat[:best[1]], flat[best[1]:]]
        cues.append({'start': words[cur[0]]['s'] - 2, 'end': words[cur[-1]]['e'] + 6, 'lines': lines})
        cur.clear()

    card_ranges = S.card_ranges
    for i, w in enumerate(words):
        if cur:
            prev = words[cur[-1]]
            gapf = w['s'] - prev['e']
            text = ' '.join(words[j]['w'] for j in cur + [i])
            durf = w['e'] - words[cur[0]]['s']
            sentence_end = prev['w'][-1:] in '.?!…' and len(' '.join(words[j]['w'] for j in cur)) > 24
            in_card = any(a <= w['s'] < b + 1 for a, b in card_ranges) != any(a <= prev['s'] < b + 1 for a, b in card_ranges)
            jump = abs((w['ts'] - prev['ts']) - (w['s'] - prev['s']) / FPS) > 0.3 or w['src'] != prev['src']  # a cut between them
            if gapf > 8 or len(text) > 2 * maxc - 4 or durf > 140 or sentence_end or w['spk'] != prev['spk'] or \
                    w['s'] - prev['s'] > 60 or in_card or jump:
                flush()
        cur.append(i)
    flush()
    for c in cues:
        c['start'] = max(0, c['start'])
        c['end'] = max(c['end'], c['start'] + 12)
    for a, b in zip(cues, cues[1:]):
        if b['start'] < a['end']:
            a['end'] = max(a['start'] + 4, b['start'])
            if b['start'] < a['end']:
                b['start'] = a['end']
    # key word pill (~35-40 % of cues)
    keyterms = X.cfg.get('pill_keyterms', [])
    for n, c in enumerate(cues):
        idx = [j for ln in c['lines'] for j in ln]
        pick = None
        for j in idx:
            base = re.sub(r'[^\w\-.]', '', words[j]['w'].lower())
            if any(base.startswith(k) for k in keyterms):
                pick = j
                break
        if pick is None and n % 3 != 1:
            cands = [j for j in idx if len(re.sub(r'\W', '', words[j]['w'])) >= 7 and re.sub(r'\W', '', words[j]['w'].lower()) not in X.stop]
            if not cands:
                cands = [j for j in idx if re.search(r'\d', words[j]['w'])]
            if cands:
                pick = max(cands, key=lambda j: len(words[j]['w']))
        if pick is not None and (n % 5 not in (2, 4) or any(re.sub(r'[^\w]', '', words[pick]['w'].lower()).startswith(k) for k in keyterms)):
            words[pick]['key'] = True
    capwords = [{k: v for k, v in w.items() if k in ('w', 's', 'e', 'key')} for w in words]
    return cues, capwords
