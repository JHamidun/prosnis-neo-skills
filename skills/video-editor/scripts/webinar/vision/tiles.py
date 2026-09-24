"""Deterministic tile-strip analysis on every 2-s frame: which strip slots carry live camera video (no model).
Geometry of the Zoom participant strip (4K px) per vision tag: job.json zoom.strip = {"P1": {"x0": 3440,
"slot_h": 223.5, "slots": 6}, "P2": {"x0": 3504, "slot_h": 187.8, "slots": 8}} (reference webinar, measured on a
probe frame: the strip moves when Zoom changes the share mode, so measure every part). Auto-detection of the strip
is NOT implemented - measure it on one 4K frame per part.
usage: python tiles.py --job job.json"""
import glob, json, os, sys
import numpy as np
from PIL import Image
import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
ROOT = f"{J.root}/vision"
GEOM = J.need("zoom.strip")  # 4K px: strip x0, slot height, max slots
def analyze(tag):
    g = GEOM[tag]; sx = 1280 / 3840
    fs = sorted(glob.glob(f"{ROOT}/frames/{tag}/{tag}_*/t_*.jpg"), key=lambda f: float(os.path.basename(f)[2:-4]))
    out = []
    for f in fs:
        t = float(os.path.basename(f)[2:-4])
        a = np.asarray(Image.open(f).convert("RGB")).astype(np.float32)
        x0 = int(g["x0"] * sx) + 3
        row = {"t": t, "slots": []}
        for k in range(g["slots"]):
            y0 = int(k * g["slot_h"] * sx) + 2; y1 = int((k + 1) * g["slot_h"] * sx * 0.78)
            y1 = int(k * g["slot_h"] * sx + g["slot_h"] * sx * 0.78)
            reg = a[y0:y1, x0:1277]
            if reg.size == 0:
                row["slots"].append(None); continue
            std = float(reg.std(axis=(0, 1)).mean())
            mx, mn = reg.max(axis=2), reg.min(axis=2)
            sat = float(((mx - mn) / (mx + 1)).mean())
            bright = float(reg.mean())
            row["slots"].append([round(std, 1), round(sat, 3), round(bright, 1)])
        out.append(row)
    json.dump(out, open(f"{ROOT}/tiles_{tag}.json", "w"), indent=0)
    return out
if __name__ == "__main__":
    for tag in GEOM:
        o = analyze(tag)
        print(tag, len(o))
        for r in o[::60]:
            print(" ", r["t"], r["slots"][:4])
