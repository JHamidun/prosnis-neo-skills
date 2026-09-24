"""S10/S13: EXTERNAL validation of edl/edl.json (independent checks, not a re-read of the builder).

Coverage (no gaps/overlaps), plan keys, files, source ranges, cameras, captions, chat privacy, sensitive crops, polls,
chapters - plus two checks added after the reference run found the defects in rendered chunks:
  * cam sync (G-E6): every camera frame shows the same source time as the voice piece under it (tolerance 1 f);
  * sketch gap (G-E5): a live sketch feed draws its first element within 50 f of its start (no empty canvas).
Writes edl/report_validate.json and edl/timeline_readable.txt. Exit code 1 when there are errors.

edl_config.json "validate" (optional):
  {"chapters": [10, 18],                              allowed number of chapter cards
   "tabbar_windows": [{"clip": "full/clips/p2_main.mp4", "from_s": 4250, "to_s": 4540, "min_y": 119}],
                                                      Zoom share with a browser tab strip: crop/moves must stay below it
   "clip_durations": {"full/clips/p1_cam2.mp4": 658.76}}   when the clip files are not rendered yet
usage: python validate_edl.py --job job.json [edl.json]
"""
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
OUT = Path(J.p('edl'))
PUB = Path(J.rel(J.get('remotion.public_dir') or 'remotion/public'))
FPS = J.fps
TOK = json.load(open(J.p('style/tokens.json'), encoding='utf-8'))
CFG = J.data('edl/edl_config.json', {})
VC = CFG.get('validate', {}) or {}
E = json.load(open(sys.argv[1] if len(sys.argv) > 1 else OUT / 'edl.json', encoding='utf-8'))
D = E['durationInFrames']
errs, warns, info = [], [], {}


def tc(f):
    s = int(f / FPS)
    return f'{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}.{int(f % FPS):02d}'


def dur_of(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def ref_durations():
    """expected clip lengths from job.json sources when the clip files do not exist yet"""
    out = dict(VC.get('clip_durations', {}) or {})
    clips = CFG.get('clips', {})
    for kind in ('main', 'cam'):
        for src, f in (clips.get(kind) or {}).items():
            try:
                out.setdefault(f, J.dur(src))
            except Exception:  # noqa: BLE001 - source not reachable: no reference length
                pass
    for src, c in ((CFG.get('cam2') or {}).get('clips') or {}).items():
        try:
            end = c['live'][1] if c.get('live') and c['live'][1] is not None else J.dur(src)
            out.setdefault(c['file'], end - c['start'])
        except Exception:  # noqa: BLE001
            pass
    return out


# ---- pieces + cards contiguous
seq = sorted([('p', x['from'], x['to'], x) for x in E['pieces']] + [('c', x['from'], x['to'], x) for x in E['cards']], key=lambda x: x[1])
teaser_end = seq[0][1]
for a, b in zip(seq, seq[1:]):
    if a[2] != b[1]:
        errs.append(f'timeline gap/overlap between {a[0]}@{tc(a[1])}-{tc(a[2])} and {b[0]}@{tc(b[1])}')
for p in E['pieces']:
    n = p['to'] - p['from']
    if abs(n - round((p['t1'] - p['t0']) * FPS)) > 1:
        errs.append(f'piece length mismatch {p}')
bend = seq[-1][2]
info['teaser_frames'] = teaser_end
info['broadcast_end'] = bend
info['outro_from'] = E['outro']['from']
if not (bend - 1 <= E['outro']['from'] <= bend + 25):
    errs.append('outro not right after the broadcast')
if E['outro']['from'] + TOK['outro']['duration_s'] * FPS != D:
    errs.append('duration != outro end')

# ---- feed coverage for every frame of the teaser+broadcast (cards excepted in their inner part)
cover = [0] * D
for fd in E['feeds']:
    if fd['to'] <= fd['from']:
        errs.append(f"empty feed {fd['id']}")
    for f in range(max(0, fd['from']), min(D, fd['to'])):
        cover[f] += 1
cards = [(c['from'], c['to']) for c in E['cards']]
gaps = []
f = min(fd['from'] for fd in E['feeds']) if E['feeds'] else 0
first_feed = f
while f < bend:
    if cover[f] == 0 and not any(a + 12 <= f < b - 2 for a, b in cards):
        g0 = f
        while f < bend and cover[f] == 0:
            f += 1
        gaps.append((g0, f))
    f += 1
for g in gaps:
    errs.append(f'no feed {tc(g[0])}-{tc(g[1])} ({g[1] - g[0]} f)')
info['max_parallel_feeds'] = max(cover) if cover else 0

# ---- files
need = set()
for fd in E['feeds']:
    need.add(fd['src'])
    if fd.get('slideImg'):
        need.add(fd['slideImg'])
    if fd.get('sketch'):
        need.add(fd['sketch']['data'])
for c in E['cams']:
    need.add(c['src'])
for c in E['chapters']:
    if c.get('art'):
        need.add(c['art']['data'])
if E['intro'].get('art'):
    need.add(E['intro']['art']['data'])
missing = [p for p in sorted(need) if not (PUB / p).exists()]
partial = [p for p in missing if (PUB / p.replace('.mp4', '.part.mp4')).exists()]
for p in missing:
    (warns if p in partial else errs).append(f'missing file {p}' + (' (ingest still running: .part exists)' if p in partial else ''))
info['files'] = len(need)

# ---- sources in range
lens = {}
for p in sorted(need):
    if p.endswith('.mp4') and (PUB / p).exists():
        lens[p] = dur_of(PUB / p)
REF = ref_durations()
for fd in E['feeds']:
    if fd['kind'] in ('zoom', 'video'):
        L = lens.get(fd['src']) or REF.get(fd['src'])
        end = (fd.get('srcStart', 0) + fd['to'] - fd['from']) / FPS
        if L and end > L + 0.05:
            (warns if fd['kind'] == 'video' else errs).append(f"{fd['id']} {fd['src']} reads to {end:.2f}s > {L:.2f}s")
        if fd.get('srcStart', 0) < 0:
            errs.append(f"{fd['id']} negative srcStart")
for c in E['cams']:
    L = lens.get(c['src']) or REF.get(c['src'])
    end = (c['srcStart'] + c['to'] - c['from']) / FPS
    if L and end > L + 0.05:
        errs.append(f"cam {c['src']} reads to {end:.2f}s > {L:.2f}s")
    if c['srcStart'] < 0:
        errs.append(f'cam negative srcStart {c}')

# ---- sensitive crops: the main clip ends where the Zoom strip with participant names starts (ingest crop);
# a browser share inside a tab-bar window must be cropped/blurred below the tab strip (G-V5)
for fd in E['feeds']:
    if fd['kind'] != 'zoom':
        continue
    cr = fd.get('crop', [0, 0, fd['cw'], fd['ch']])
    if cr[0] + cr[2] > fd['cw'] + 0.5:
        errs.append(f"{fd['id']} crop outside clip")
    for w in VC.get('tabbar_windows', []) or []:
        if fd['src'] != w['clip'] or not (w['from_s'] < fd['srcStart'] / FPS < w['to_s']):
            continue
        if fd.get('blur') is None:
            errs.append(f"feed {fd['id']} in a tab-bar window without the tab-bar blur")
        if cr[1] < w['min_y'] - 1:
            errs.append(f"feed {fd['id']} crop shows the browser tab bar")
        for m in fd.get('moves', []):
            if m['rect'][1] < w['min_y']:
                errs.append(f"move {m} of {fd['id']} reaches into the tab bar")

# ---- layouts
keys = E['layouts']
prev = -10**9
for k in keys:
    if k['layout'] not in TOK['layout']:
        errs.append(f"unknown layout {k['layout']}")
        continue
    lt = TOK['layout'][k['layout']]
    for need_k in ('caption_band', 'lower_third_anchor'):
        if need_k not in lt:
            errs.append(f"layout {k['layout']} lacks {need_k} (Program crashes)")
    if k['frame'] <= prev:
        errs.append(f'layout keys not increasing at {k}')
    prev = k['frame']
holds = [(b['frame'] - a['frame'], a['layout'], a['frame']) for a, b in zip(keys, keys[1:])]
for h in [h for h in holds if h[0] < 3 * FPS and h[2] > 300]:
    warns.append(f'short layout hold {h[0]} f ({h[1]}) at {tc(h[2])}')
info['layout_keys'] = dict(Counter(k['layout'] for k in keys))


def layout_at(f):
    L = keys[0]['layout']
    for k in keys:
        if k['frame'] <= f:
            L = k['layout']
        else:
            break
    return L


tot = Counter()
for f in range(0, D, FPS):
    tot[layout_at(f)] += 1
info['layout_seconds'] = dict(tot)
camcov = [False] * D
for c in E['cams']:
    for f in range(max(0, c['from']), min(D, c['to'])):
        camcov[f] = True
nocam = 0
for f in range(first_feed + 10, bend, 5):
    L = layout_at(f)
    if TOK['layout'].get(L, {}).get('cam') and not camcov[f] and not any(a <= f < b for a, b in cards):
        nocam += 5
if nocam:
    warns.append(f'{nocam} frames with a cam slot but no camera clip (empty PiP hidden by Program)')
info['frames_cam_slot_without_cam'] = nocam

# ---- cam sync vs voice (G-E6)
part_of = {f_: s for s, f_ in (CFG.get('clips', {}).get('cam') or {}).items()}
dstart = {}
for s, c in ((CFG.get('cam2') or {}).get('clips') or {}).items():
    part_of[c['file']] = s
    dstart[c['file']] = c['start']
bad_sync = 0
for c in E['cams']:
    src = part_of.get(c['src'])
    if not src:
        continue
    for p in E['pieces']:
        if p['src'] != src or p['to'] <= c['from'] or p['from'] >= c['to']:
            continue
        f = max(c['from'], p['from']) + 2
        if f >= min(c['to'], p['to']):
            continue
        cam_t = (c['srcStart'] + f - c['from']) / FPS + dstart.get(c['src'], 0.0)
        voice_t = p['t0'] + (f - p['from']) / FPS
        if abs(cam_t - voice_t) > 1.01 / FPS:
            bad_sync += 1
            if bad_sync <= 20:
                errs.append(f"cam {c['src']} at {tc(f)} shows {cam_t:.2f}s, voice is {voice_t:.2f}s ({(cam_t - voice_t) * FPS:+.0f} f)")
info['cam_sync_errors'] = bad_sync

# ---- sketch gap (G-E5)
for fd in E['feeds']:
    if fd['kind'] == 'sketch' and fd.get('sketch', {}).get('beats'):
        first = min(fd['sketch']['beats'].values())
        if first - fd['from'] > 50 and fd['sketch'].get('settle', 0) < 10**6:
            errs.append(f"sketch {fd['id']} at {tc(fd['from'])}: empty canvas for {first - fd['from']} f before the first element")

# ---- captions
W = E['words']
for a, b in zip(E['cues'], E['cues'][1:]):
    if b['start'] < a['end']:
        errs.append(f"cue overlap at {tc(b['start'])}")
for c in E['cues']:
    if c['end'] > D or c['start'] < 0:
        errs.append(f"cue outside video {c}")
    for ln in c['lines']:
        for j in ln:
            if not (0 <= j < len(W)):
                errs.append('cue index out of range')
if any(w['s'] > W[i + 1]['s'] for i, w in enumerate(W[:-1])):
    errs.append('words not monotonic')
drop = [w.lower() for w in (CFG.get('drop_words') or J.get('transcript.drop_words', []) or [])]
if drop:
    rx_drop = re.compile('|'.join(re.escape(w[:max(4, len(w) - 2)]) for w in drop), re.I)  # stem: catches the case forms
    bad = [w['w'] for w in W if rx_drop.search(w['w'])]
    if bad:
        errs.append(f'private surname in subtitles: {bad}')
info['cues'] = len(E['cues'])
info['subtitle_last_end'] = tc(max(c['end'] for c in E['cues'])) if E['cues'] else None
info['key_share'] = round(sum(1 for c in E['cues'] if any(W[j].get('key') for ln in c['lines'] for j in ln)) / max(1, len(E['cues'])), 3)

# ---- chat privacy
rx = re.compile(r'@\w|https?://|www\.|\.ru\b|\.com\b|\+?\d[\d\s\-()]{8,}\d|[\w.]+@[\w.]+')
for it in E['chat']:
    if rx.search(it['text']) or rx.search(it['name']):
        errs.append(f"chat privacy: {it['name']}: {it['text'][:60]}")
    if len(it['name'].split()) > 1 and it['name'] != 'Участник':
        warns.append(f"chat name with 2 words: {it['name']}")
info['chat'] = len(E['chat'])
info['chat_names'] = sorted({it['name'] for it in E['chat']})

# ---- polls
ps = sorted(E['polls'], key=lambda p: p['from'])
for a, b in zip(ps, ps[1:]):
    if b['from'] < a['to'] + 14:
        errs.append(f"polls overlap {a['id']} / {b['id']}")
info['polls'] = [(p['id'], tc(p['from']), len(p['votes'])) for p in ps]

# ---- chapters/heroes/winners don't collide
card_len = TOK['chapter_card']['duration_frames']
for c in E['chapters']:
    for h in E['heroes'] + E['winners']:
        if h['from'] < c['from'] + card_len and c['from'] < h['to']:
            errs.append(f"hero/winner over chapter card {c['n']}")
lo, hi = VC.get('chapters', [1, 40])
if not (lo <= len(E['chapters']) <= hi):
    errs.append(f'chapter count {len(E["chapters"])} out of range {lo}-{hi}')
for h in E['heroes']:
    if any(w['from'] < h['to'] and h['from'] < w['to'] for w in E['winners']):
        errs.append('hero over winner')

# ---- readable timeline
ev = []
for k in keys:
    ev.append((k['frame'], f"LAYOUT {k['layout']}"))
for fd in E['feeds']:
    extra = ''
    if fd['kind'] == 'sketch':
        extra = f" sketch({len(fd['sketch']['beats'])} el)"
    if fd.get('marks'):
        extra += ' marks:' + ','.join(m['type'] for m in fd['marks'])
    if fd.get('moves'):
        extra += f" moves:{len(fd['moves'])}"
    ev.append((fd['from'], f"FEED {fd['kind']:6s} {fd['src']}{extra} (to {tc(fd['to'])})"))
for c in E['chapters']:
    ev.append((c['from'], f"CHAPTER {c['n']} {' '.join(c['lines'])} art={bool(c.get('art'))} {c['fromLayout']}->{c['toLayout']}"))
for h in E['heroes']:
    ev.append((h['from'], f"HERO «{h['text']}»"))
for p in E['polls']:
    ev.append((p['from'], f"POLL {p['title']} ({len(p['votes'])} votes, to {tc(p['to'])})"))
for d in E['doodles']:
    ev.append((d['from'], f"DOODLE {d['type']} {d.get('text', '')!r}"))
for w in E['winners']:
    ev.append((w['from'], f"WINNER {w['kicker']} {w['name']}"))
for lt in E['lowerThirds']:
    ev.append((lt['from'], f"LOWER3 {lt['person']}"))
for t in E['tags'] + E['chips']:
    ev.append((t['from'], f"TAG {t['text']}"))
for p in E['pieces']:
    ev.append((p['from'], f"PIECE {p['src']} {p['t0']:.2f}-{p['t1']:.2f}"))
ev.sort(key=lambda x: x[0])
(OUT / 'timeline_readable.txt').write_text('\n'.join(f'{tc(f)}  {s}' for f, s in ev), encoding='utf-8', newline='\n')

rep = {'ok': not errs, 'errors': errs, 'warnings': warns[:200], 'n_warnings': len(warns), 'info': info}
with open(OUT / 'report_validate.json', 'w', encoding='utf-8', newline='\n') as fh:
    json.dump(rep, fh, ensure_ascii=False, indent=1)
print('ERRORS', len(errs))
for e in errs[:40]:
    print('  E', e)
print('WARNINGS', len(warns))
for w in warns[:25]:
    print('  W', w)
print(json.dumps({k: v for k, v in info.items() if k != 'chat_names'}, ensure_ascii=False)[:1500])
sys.exit(1 if errs else 0)
