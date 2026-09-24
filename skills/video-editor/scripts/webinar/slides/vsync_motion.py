"""S7: sync SILENT deck videos to the recording by motion-energy cross-correlation (10 fps) -> edl/vsync_vis.json.

The screen share of the recording (1080p proxy) is cropped to the rectangle where the video plays on the slide,
both are reduced to 48x27 grey, frame-difference energy is z-scored and slid over each other.
Weak matches (corr < 0.4) are not trusted: the builder then starts the clean video at the slide start.

job.json deck.videos[] (mode "motion"):
  {"key": "54", "mode": "motion", "src": "part2", "window": [2825, 80], "crop": [0.44, 0.34, 0.5, 0.5],
   "video": "<clean>.mp4"}
  crop = [x, y, w, h] as fractions of the 1920x1080 proxy (take it from the pptx: manus-slides/scripts/pptx_video_rects.py)
Proxy: proxy/<src>.mp4 (sources/proxies.py).
Output: {key: {part, video, rec_time_of_video_t0, corr, window}}
usage: python vsync_motion.py --job job.json [key ...]
"""
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load, low_flags  # noqa: E402

J = load()
FPS = 10
W, H = 48, 27


def frames(path, ss=None, t=None, crop=None):
    cmd = ['ffmpeg', '-v', 'error']
    if ss is not None:
        cmd += ['-ss', f'{ss:.3f}']
    cmd += ['-i', path]
    if t is not None:
        cmd += ['-t', f'{t:.3f}']
    vf = (f'crop={crop},' if crop else '') + f'fps={FPS},scale={W}:{H},format=gray'
    cmd += ['-an', '-vf', vf, '-f', 'rawvideo', '-']
    b = subprocess.run(cmd, capture_output=True, **low_flags()).stdout
    return np.frombuffer(b, dtype=np.uint8).reshape(-1, H, W).astype(np.float32)


def energy(fr):
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
    d = np.concatenate([[0], d])
    return (d - d.mean()) / (d.std() + 1e-6)


def main():
    want = set(sys.argv[1:])
    out_p = J.p('edl/vsync_vis.json')
    out = json.load(open(out_p, encoding='utf-8')) if os.path.exists(out_p) else {}
    for v in J.get('deck.videos', []) or []:
        if v.get('mode') != 'motion' or (want and v['key'] not in want):
            continue
        k = v['key']
        if k in out and not want:
            print(k, 'skip')
            continue
        part = v['src']
        ss, t = v['window']
        r = v.get('crop', [0, 0, 1, 1])
        vid = J.rel(v['video'])
        x, y, w, h = [int(q) for q in (r[0] * 1920, r[1] * 1080, r[2] * 1920, r[3] * 1080)]
        a = energy(frames(J.p(f'proxy/{part}.mp4'), ss, t, f'{w}:{h}:{x}:{y}'))
        vlen = min(t * 0.8, 30)
        b = energy(frames(vid, 0, vlen))
        best = (-9, 0)
        for L in range(0, len(a) - len(b) + 1):
            c = float(np.dot(a[L:L + len(b)], b) / len(b))
            if c > best[0]:
                best = (c, L)
        out[k] = {'part': part, 'video': vid, 'rec_time_of_video_t0': round(ss + best[1] / FPS, 2),
                  'corr': round(best[0], 3), 'window': [ss, ss + t]}
        print(k, out[k], flush=True)
        os.makedirs(os.path.dirname(out_p), exist_ok=True)
        with open(out_p, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(out, f, indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
