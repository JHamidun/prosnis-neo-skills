"""Frame-accurate refinement of frame-pass boundaries (2 s grid -> 1/25 s).

For each boundary t_b (first 2-s frame showing the new state), decode the 4K source in
[t_b-2.4, t_b+0.2] at native 25 fps (GPU decode, 128x72 gray) and take the frame with the
largest mean abs diff vs the previous frame. Checkpoint: bounds_<tag>.json (skip-if-done).
Then fix_monotonic(tag): rapid flips (3 slides in 2 s) can resolve two grid boundaries to one peak (G-V4).
usage: python refine_bounds.py --job job.json [P1 P2]   (python -c "import refine_bounds as r; r.fix_monotonic('P2')")
"""
import json, os, subprocess, sys, glob
from concurrent.futures import ThreadPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from runs import runs

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
ROOT = f"{J.root}/vision"
SOURCES = {tag: J.src(sid) for tag, sid in J.vision_tags().items()}
W, H, FPS = 128, 72, 25


def refine(tag, tb):
    s = max(0.0, tb - 2.4)
    cmd = ["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
           "-ss", f"{s:.3f}", "-i", SOURCES[tag], "-t", "2.6", "-an",
           "-vf", f"scale_cuda={W}:{H},hwdownload,format=nv12,format=gray", "-f", "rawvideo", "-"]
    p = subprocess.run(cmd, capture_output=True, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    buf = np.frombuffer(p.stdout, dtype=np.uint8)
    n = len(buf) // (W * H)
    if n < 3:
        return {"t_grid": tb, "t": tb, "conf": 0.0, "note": "decode failed"}
    fr = buf[: n * W * H].reshape(n, H, W).astype(np.float32)
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
    i = int(d.argmax())
    med = float(np.median(d)) + 0.05
    return {"t_grid": tb, "t": round(s + (i + 1) / FPS, 3), "peak": round(float(d[i]), 2),
            "conf": round(float(d[i]) / med, 1), "frames": n}


def main(tag):
    out = f"{ROOT}/bounds_{tag}.json"
    done = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    rs = runs(tag)
    tbs = [r["t"] for r in rs[1:]]
    todo = [t for t in tbs if f"{t:.1f}" not in done]
    print(tag, "boundaries", len(tbs), "todo", len(todo), flush=True)
    with ThreadPoolExecutor(4) as ex:
        for t, res in zip(todo, ex.map(lambda t: refine(tag, t), todo)):
            done[f"{t:.1f}"] = res
            json.dump(done, open(out, "w", encoding="utf-8"), indent=0)
    print(tag, "done", flush=True)


if __name__ == "__main__":
    for tag in (sys.argv[1:] or list(SOURCES)):
        main(tag)
    print("ALL DONE", flush=True)


def window_peak(tag, s, e):
    cmd = ["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
           "-ss", f"{s:.3f}", "-i", SOURCES[tag], "-t", f"{e - s:.3f}", "-an",
           "-vf", f"scale_cuda={W}:{H},hwdownload,format=nv12,format=gray", "-f", "rawvideo", "-"]
    p = subprocess.run(cmd, capture_output=True, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    buf = np.frombuffer(p.stdout, dtype=np.uint8)
    n = len(buf) // (W * H)
    fr = buf[: n * W * H].reshape(n, H, W).astype(np.float32)
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
    i = int(d.argmax())
    return round(s + (i + 1) / FPS, 3), round(float(d[i]), 2)


def fix_monotonic(tag):
    """Rapid slide flips: two grid boundaries 2 s apart can resolve to the same peak. Re-search the
    later one strictly after the earlier one."""
    out = f"{ROOT}/bounds_{tag}.json"
    d = json.load(open(out, encoding="utf-8"))
    keys = sorted(d, key=float)
    prev = None
    for k in keys:
        b = d[k]
        if prev is not None and b["t"] <= prev["t"] + 0.1:
            t, pk = window_peak(tag, prev["t"] + 0.08, float(k) + 0.6)
            b.update({"t": t, "peak": pk, "note": f"rapid flip: re-searched after previous boundary {prev['t']}"})
            print(tag, k, "->", t, pk, flush=True)
        prev = b
    json.dump(d, open(out, "w", encoding="utf-8"), indent=0)
