"""S11/S13: provenance of every rendered chunk - which worker rendered it, when the render STARTED (= which version of
the chunk EDL it read) and from which bundle. Needed as soon as the EDL is fixed while the render runs (the reference
run fixed sketch gaps and camera sync mid-render and had to withdraw 18 chunks).

A chunk is VALID only if
  * its render started after the last change of its chunk EDL (edl/chunks/changes.jsonl, written by split_chunks.py;
    fallback: the chunk json mtime), and
  * the worker's bundle is newer than the last change of style/tokens.json and of the template src/ (tokens and code
    are baked into the bundle, G-R2) - bundle from the worker sidecar worker_<name>.json (start_workers.ps1).
Worker log lines: "[HH:MM:SS +Ns <worker>] START chunk_NNN ..." / "... DONE chunk_NNN ..." (render_worker.mjs).
The date of the log lines is taken from the sidecar start (renders crossing midnight: pass --day YYYY-MM-DD).

usage: python provenance.py --job job.json [--day 2026-09-24] [--withdraw]
  --withdraw  move INVALID chunk mp4s to render/withdrawn/ so the running workers re-render them (they skip only
              existing mp4s); never touches valid chunks
-> prints a table, writes render/provenance.json; exit 1 if any chunk is invalid or unknown
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
REN = Path(J.p('render'))
CH = Path(J.p('edl/chunks'))
IDX = json.load(open(CH / 'index.json', encoding='utf-8'))
DAY = sys.argv[sys.argv.index('--day') + 1] if '--day' in sys.argv else None


def last_change():
    out = {}
    p = CH / 'changes.jsonl'
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                out[r['id']] = max(out.get(r['id'], datetime.min), datetime.fromisoformat(r['at']))
    for c in IDX['chunks']:
        if c['id'] not in out:
            out[c['id']] = datetime.fromtimestamp(Path(c['file']).stat().st_mtime)
    return out


def code_mtime():
    """latest change of what is baked into a bundle: style/tokens.json + remotion/src/**"""
    ts = [Path(J.p('style/tokens.json')).stat().st_mtime]
    src = Path(J.rel(J.get('remotion.dir') or 'remotion')) / 'src'
    ts += [p.stat().st_mtime for p in src.rglob('*') if p.is_file()]
    return datetime.fromtimestamp(max(ts))


def main():
    changed = last_change()
    baked = code_mtime()
    sidecars = {}
    for s in REN.glob('worker_*.json'):
        try:
            d = json.loads(s.read_text(encoding='utf-8-sig'))
            sidecars[d['name']] = d
        except Exception:  # noqa: BLE001
            pass
    events = []
    for log in REN.glob('worker_*.log'):
        wname = log.stem.replace('worker_', '')
        side = sidecars.get(wname, {})
        day = DAY or (side.get('started', '')[:10] or time.strftime('%Y-%m-%d'))
        for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
            m = re.match(r'\[(\d\d:\d\d:\d\d) \+\d+s (\S+)\] (START|DONE) (chunk_\d{3}|\S+)', line)
            if m:
                events.append((datetime.fromisoformat(f'{day} {m.group(1)}'), wname, m.group(3), m.group(4)))
    events.sort()
    rows, bad = [], 0
    for c in IDX['chunks']:
        name = c['id'].replace('full_', 'chunk_')
        p = REN / f'{name}.mp4'
        if not p.exists():
            rows.append({'chunk': name, 'status': 'missing'})
            continue
        mt = datetime.fromtimestamp(p.stat().st_mtime)
        dones = [e for e in events if e[3] == name and e[2] == 'DONE' and abs((e[0] - mt).total_seconds()) < 90]
        if not dones:
            rows.append({'chunk': name, 'status': 'UNKNOWN provenance', 'mtime': mt.strftime('%H:%M:%S')})
            bad += 1
            continue
        d = dones[-1]
        starts = [e for e in events if e[3] == name and e[2] == 'START' and e[1] == d[1] and e[0] <= d[0]]
        st = starts[-1][0] if starts else None
        side = sidecars.get(d[1], {})
        bundle_t = datetime.fromisoformat(side['bundle_mtime']) if side.get('bundle_mtime') else None
        problems = []
        if st is None:
            problems.append('no START')
        elif st < changed[c['id']]:
            problems.append(f'started {st:%H:%M:%S} before its EDL changed {changed[c["id"]]:%H:%M:%S}')
        if bundle_t is None:
            problems.append('bundle unknown (no worker sidecar)')
        elif bundle_t < baked:
            problems.append(f'bundle {bundle_t:%H:%M:%S} older than tokens/src {baked:%H:%M:%S}')
        if problems:
            bad += 1
            if '--withdraw' in sys.argv:
                dst = REN / 'withdrawn'
                dst.mkdir(exist_ok=True)
                p.replace(dst / f'{name}.{int(time.time())}.mp4')
                problems.append('withdrawn')
        rows.append({'chunk': name, 'worker': d[1], 'bundle': side.get('bundle', '?'), 'start': st and st.strftime('%H:%M:%S'),
                     'done': d[0].strftime('%H:%M:%S'), 'status': 'OK' if not problems else 'BAD: ' + '; '.join(problems)})
    for r in rows:
        print(r)
    with open(REN / 'provenance.json', 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
