"""S10: split edl/edl.json into render chunks (default 7500 frames = 5 min at 25 fps) for the render workers.

Every chunk is a self-contained Program EDL on its own clock (frame 0 = chunk start). Everything is re-based by -c0
and KEEPS its original relative timing, so springs, drifts, morphs, sketch beats and chat reflow continue seamlessly
across chunk boundaries (G-R7):
  * layouts: the key active at c0 and the one before it (a morph in progress) are kept (negative frames);
  * feeds / cams: kept with negative `from` (Remotion Sequence accepts a negative from; srcStart unchanged);
  * chat: the last 10 bubbles before c0 are kept (negative frames) so the column is full at the cut;
  * polls: kept whole while they overlap the chunk (votes before c0 count already);
  * captions: cues overlapping the chunk, their words re-indexed.
Cut points: every N frames, nudged (+-150 f) to a frame with no layout morph / chapter card in progress.
Writes are atomic (tmp + os.replace): render workers may be reading chunk files while an EDL fix is re-split.

usage: python split_chunks.py --job job.json [chunk_frames]      (default: job.json render.chunk_frames or 7500)
       -> edl/chunks/full_NNN.json + edl/chunks/index.json
As a module (make_tests.py): import split_chunks as S; S.load(); S.chunk(k, c0, c1)
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load as load_job  # noqa: E402

J = load_job()
OUT = Path(J.p('edl'))
CH = OUT / 'chunks'
NL = chr(10)  # LF on every OS (G-W1)
PAD = 120  # items that start up to PAD frames before the chunk and are still animating
E: dict = {}
D = 0


def load(path=None):
    """load the master EDL (edl/edl.json or another EDL file) into the module globals E, D"""
    global E, D
    E = json.load(open(path or (OUT / 'edl.json'), encoding='utf-8'))
    D = E['durationInFrames']
    return E


def save(path, obj):
    tmp = Path(str(path) + '.tmp')
    with open(tmp, 'w', encoding='utf-8', newline=NL) as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def overl(a, b, c0, c1):
    return a < c1 and b > c0


def sh(x, c0):
    return x - c0


def chunk(k, c0, c1):
    e = {'id': f'full_{k:03d}', 'durationInFrames': c1 - c0, 'chunk': {'index': k, 'from': c0, 'to': c1, 'of': D}}
    # layouts
    L = E['layouts']
    i = max(0, max((j for j, x in enumerate(L) if x['frame'] <= c0), default=0) - 1)
    lays = [dict(x, frame=x['frame'] - c0) for x in L[i:] if x['frame'] < c1]
    e['layouts'] = lays
    e['feeds'] = []
    for fd in E['feeds']:
        if overl(fd['from'], fd['to'], c0, c1):
            d = json.loads(json.dumps(fd))
            d['from'] -= c0
            d['to'] -= c0
            for m in d.get('moves', []):
                m['frame'] -= c0
            for m in d.get('marks', []):
                m['from'] -= c0
                if 'to' in m:
                    m['to'] -= c0
            for b in d.get('blur', []):
                if 'from' in b:
                    b['from'] -= c0
                if 'to' in b:
                    b['to'] -= c0
            for p in d.get('pulse', []):
                p['from'] -= c0
            if d.get('sketch'):
                d['sketch']['beats'] = {k2: v - c0 for k2, v in d['sketch']['beats'].items()}
                if 'settle' in d['sketch'] and d['sketch']['settle'] < 10**6:
                    d['sketch']['settle'] -= c0
            e['feeds'].append(d)
    e['cams'] = [dict(c, **{'from': c['from'] - c0, 'to': c['to'] - c0}) for c in E['cams'] if overl(c['from'], c['to'], c0, c1)]
    # captions
    cues = [c for c in E['cues'] if overl(c['start'], c['end'], c0, c1)]
    idx = sorted({j for c in cues for ln in c['lines'] for j in ln})
    remap = {j: n for n, j in enumerate(idx)}
    e['words'] = [dict(E['words'][j], s=E['words'][j]['s'] - c0, e=E['words'][j]['e'] - c0) for j in idx]
    e['cues'] = [{'start': c['start'] - c0, 'end': c['end'] - c0, 'lines': [[remap[j] for j in ln] for ln in c['lines']]} for c in cues]
    e['heroes'] = [dict(h, **{'from': h['from'] - c0, 'to': h['to'] - c0}) for h in E['heroes'] if overl(h['from'], h['to'] + 10, c0, c1)]
    # chat: history + chunk
    before = [it for it in E['chat'] if it['frame'] < c0][-10:]
    inside = [it for it in E['chat'] if c0 <= it['frame'] < c1]
    e['chat'] = []
    for it in before + inside:
        d = json.loads(json.dumps(it))
        d['frame'] -= c0
        for r in d.get('reacts', []) or []:
            r['frame'] -= c0
        for a in d.get('aggregate', []) or []:
            a['frame'] -= c0
        e['chat'].append(d)
    e['polls'] = []
    for p in E['polls']:
        if overl(p['from'] - 2, p['to'] + 16, c0, c1):
            d = json.loads(json.dumps(p))
            d['from'] -= c0
            d['to'] -= c0
            for v in d['votes']:
                v['frame'] -= c0
            if d.get('reveal'):
                d['reveal']['frame'] -= c0
            e['polls'].append(d)
    e['reactions'] = [dict(r, frame=r['frame'] - c0) for r in E['reactions'] if c0 - 80 <= r['frame'] < c1]
    e['lowerThirds'] = [dict(x, **{'from': x['from'] - c0, 'to': x['to'] - c0}) for x in E['lowerThirds'] if overl(x['from'], x['to'], c0, c1)]
    e['doodles'] = [dict(x, **{'from': x['from'] - c0, **({'to': x['to'] - c0} if 'to' in x else {})}) for x in E['doodles'] if overl(x['from'], x.get('to', x['from'] + 250), c0, c1)]
    e['chapters'] = [dict(x, **{'from': x['from'] - c0}) for x in E['chapters'] if overl(x['from'], x['from'] + 96, c0, c1)]
    e['winners'] = [dict(x, **{'from': x['from'] - c0, 'to': x['to'] - c0}) for x in E['winners'] if overl(x['from'], x['to'] + 10, c0, c1)]
    e['confetti'] = [dict(x, frame=x['frame'] - c0) for x in E['confetti'] if c0 - 150 <= x['frame'] < c1]
    e['chips'] = [dict(x, **{'from': x['from'] - c0, 'to': x['to'] - c0}) for x in E['chips'] if overl(x['from'], x['to'], c0, c1)]
    e['tags'] = [dict(x, **{'from': x['from'] - c0, 'to': x['to'] - c0}) for x in E['tags'] if overl(x['from'], x['to'], c0, c1)]
    if c0 < E['intro']['titleTo'] + 5:
        e['intro'] = E['intro']
    if E.get('outro') and E['outro']['from'] < c1:
        e['outro'] = {'from': E['outro']['from'] - c0}
    e['fadeOut'] = 0
    return e


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else int(J.get('render.chunk_frames', 7500))
    load()
    CH.mkdir(parents=True, exist_ok=True)
    busy = set()
    for x in E['layouts']:
        busy.update(range(x['frame'] - 2, x['frame'] + x.get('morph', 15) + 2))
    for c in E['chapters']:
        busy.update(range(c['from'] - 5, c['from'] + 100))
    cuts = [0]
    t = N
    while t < D - N // 3:
        best = t
        for d in range(0, 151):
            for cand in (t + d, t - d):
                if cand not in busy:
                    best = cand
                    break
            else:
                continue
            break
        cuts.append(best)
        t = best + N
    cuts.append(D)
    idx = []
    for k, (a, b) in enumerate(zip(cuts, cuts[1:])):
        e = chunk(k, a, b)
        path = CH / f"{e['id']}.json"
        new = json.dumps(e, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        old = path.read_bytes() if path.exists() else None
        if old != new:  # provenance: when did this chunk's EDL last change (render/provenance.py)
            with open(CH / 'changes.jsonl', 'a', encoding='utf-8', newline=NL) as f:
                f.write(json.dumps({'id': e['id'], 'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                    'md5': hashlib.md5(new).hexdigest(), 'was': hashlib.md5(old).hexdigest() if old else None}) + NL)
        save(path, e)
        idx.append({'id': e['id'], 'from': a, 'to': b, 'frames': b - a, 'file': str(path).replace(chr(92), '/'), 'feeds': len(e['feeds']),
                    'kb': round(path.stat().st_size / 1024)})
    assert sum(c['frames'] for c in idx) == D
    tmp = CH / 'index.json.tmp'
    with open(tmp, 'w', encoding='utf-8', newline=NL) as f:
        json.dump({'fps': J.fps, 'total_frames': D, 'chunk_frames': N, 'chunks': idx}, f, indent=1)
    os.replace(tmp, CH / 'index.json')
    print(len(idx), 'chunks', [c['frames'] for c in idx][:5], '... max kb', max(c['kb'] for c in idx))


if __name__ == '__main__':
    main()
