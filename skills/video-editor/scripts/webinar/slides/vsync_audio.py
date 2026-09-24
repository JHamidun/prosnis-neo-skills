"""S7: sync the clean deck videos WITH SOUND to the recording by audio cross-correlation -> edl/vsync.json.

The Program shows the clean original video file instead of its blurry Zoom share; the builder needs the recording
time at which the video's t=0 played. Two probes per video (the main window and 15 s after it) - they must agree.

job.json deck.videos[] (mode "audio"):
  {"key": "12", "mode": "audio", "src": "part1", "window": [760, 180], "video": "<clean>.mp4", "probe": [5, 40]}
  window = [start_s, dur_s] in the recording (source src) where the video plays; probe = [start_s, dur_s] inside
  the clean video that is compared. Recording audio: audio/<src>_16k.wav (sources/proxies.py).
Output: {key: {video, rec_time_of_video_t0, quality, probe, check_t0, check_q}}; quality = peak / median |xcorr|.
usage: python vsync_audio.py --job job.json [key ...]
"""
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load, low_flags  # noqa: E402

J = load()
SR = 8000


def pcm(path, ss=None, t=None):
    cmd = ['ffmpeg', '-v', 'error']
    if ss is not None:
        cmd += ['-ss', str(ss)]
    cmd += ['-i', path]
    if t is not None:
        cmd += ['-t', str(t)]
    cmd += ['-vn', '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-']
    return np.frombuffer(subprocess.run(cmd, capture_output=True, **low_flags()).stdout, dtype=np.float32)


def xcorr(a, b):
    """lag L so that a[n+L] ~ b[n] (b = clean video audio, a = recording window)."""
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    A = np.fft.rfft(a, n)
    B = np.fft.rfft(b, n)
    c = np.fft.irfft(A * np.conj(B), n)
    L = int(np.argmax(c[:len(a)]))
    peak = c[L] / np.sqrt(len(b))
    med = np.median(np.abs(c[:len(a)])) / np.sqrt(len(b))
    return L / SR, float(peak / (med + 1e-9))


def main():
    want = set(sys.argv[1:])
    out_p = J.p('edl/vsync.json')
    out = json.load(open(out_p, encoding='utf-8')) if os.path.exists(out_p) else {}
    for v in J.get('deck.videos', []) or []:
        if v.get('mode', 'audio') != 'audio' or (want and v['key'] not in want):
            continue
        k = v['key']
        if k in out and not want:
            print(k, 'skip')
            continue
        rec = J.p(f"audio/{v['src']}_16k.wav")
        ss, t = v['window']
        vs, vt = v.get('probe', [2, 40])
        vid = J.rel(v['video'])
        a = pcm(rec, ss, t)
        b = pcm(vid, vs, vt)
        L, q = xcorr(a, b)
        start = ss + L - vs  # recording time where the clean video t=0 plays
        out[k] = {'video': vid, 'rec_time_of_video_t0': round(start, 3), 'quality': round(q, 1), 'probe': [vs, vt]}
        b2 = pcm(vid, vs + vt, 15)  # second probe for robustness
        L2, q2 = xcorr(a, b2)
        out[k]['check_t0'] = round(ss + L2 - (vs + vt), 3)
        out[k]['check_q'] = round(q2, 1)
        print(k, out[k], flush=True)
        os.makedirs(os.path.dirname(out_p), exist_ok=True)
        with open(out_p, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(out, f, indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
