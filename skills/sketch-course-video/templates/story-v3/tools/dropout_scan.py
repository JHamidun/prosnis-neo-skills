"""Scan finished story-v3 videos for 1-frame sketch-art dropouts (read-only).

A dropout is a single frame where the pencil art (hook drawing, a panel sketch, the CTA art) vanishes and comes back
on the next frame. It happens when the render tab screenshots before the art PNG is decoded (gotcha G-R13); the fix
lives in src/StoryV3.tsx + src/SketchArt.tsx, and this scan proves each finished file is clean.

    python tools/dropout_scan.py <clip> [<clip> ...]          # reads out/<clip>.mp4 + public/clips/<clip>/story.json
    python tools/dropout_scan.py s1 s2 --project D:/job/stories/project --out D:/job/stories/out

A frame counts as a dropout when the ink-pixel count in a watched window falls below 70 % of both neighbours.
Exit code 1 if any dropout is found.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
FPS = 30


def window(mp4, x, y, w, h, f0, f1):
    vf = f'select=between(n\\,{f0}\\,{f1}),crop={w}:{h}:{x}:{y},scale={w // 2}:{h // 2},format=gray'
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(mp4), '-vf', vf, '-vsync', '0', '-f', 'rawvideo', '-'],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h // 2, w // 2)


def scan(mp4, story):
    s = lambda t: round(t * FPS)  # noqa: E731
    # (x, y, w, h, first frame, last frame, dark background?) — the story-v3 layout at 1080x1920
    wins = [('hook', (72, 640, 936, 860, 0, s(story['hook']['end']), False)),
            ('cta', (170, 560, 740, 700, s(story['cta']['start']), story['frames'] - 1, True))]
    wins += [(f"panel:{k['art']}", (58, 492, 964, 556, s(k['start']), s(k['end']), False)) for k in story.get('sketches', [])]
    found = []
    for name, (x, y, w, h, f0, f1, dark) in wins:
        fr = window(mp4, x, y, w, h, f0, f1)
        ink = ((fr > 90) if dark else (fr < 150)).sum(axis=(1, 2)).astype(float)
        for i in range(1, len(ink) - 1):
            ref = min(ink[i - 1], ink[i + 1])
            if ref > 500 and ink[i] < 0.7 * ref:
                found.append((name, f0 + i, int(ink[i - 1]), int(ink[i]), int(ink[i + 1])))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clips', nargs='+')
    ap.add_argument('--project', default=str(HERE))
    ap.add_argument('--out', default=None, help='folder with <clip>.mp4 (default: <project>/out)')
    a = ap.parse_args()
    proj = Path(a.project)
    out = Path(a.out) if a.out else proj / 'out'
    bad = False
    for cid in a.clips:
        mp4 = out / f'{cid}.mp4'
        if not mp4.exists():
            print(cid, 'no mp4 at', mp4)
            bad = True
            continue
        story = json.loads((proj / 'public/clips' / cid / 'story.json').read_text(encoding='utf-8'))
        found = scan(mp4, story)
        print(cid, 'dropouts:', found or 'none', flush=True)
        bad |= bool(found)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
