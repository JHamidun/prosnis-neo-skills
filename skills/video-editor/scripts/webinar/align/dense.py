"""Dense piecewise offset map: GCC-PHAT on W-second windows every STEP s, +-MAXS search
around a coarse offset. Saves align/dense_<part><tag>.json and prints run-length summary.
usage: python dense.py --job job.json <part> <coarse_s|auto> [W=10] [STEP=10] [MAXS=6] [t_from=0] [t_to=..] [tag=_full]
  coarse 'auto' = align/xcorr_result.json -> <part>.coarse_offset_s. offmap.py reads tags _full, _head, _tail.
  Reference run: full scan W10 STEP10 MAXS6 (tag _full), plus short head/tail scans where the map was sparse."""
import json, sys
import numpy as np
import soundfile as sf
from scipy import signal

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
ROOT = J.root
SR = 16000


def load_f(name):
    x, sr = sf.read(f"{ROOT}/audio/{name}", dtype="float32")
    sos = signal.butter(4, [200, 5000], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x).astype(np.float32)


def gcc(ref, q, maxs):
    n = len(ref) + len(q)
    nfft = 1 << int(np.ceil(np.log2(n)))
    R = np.fft.rfft(ref, nfft) * np.conj(np.fft.rfft(q, nfft))
    R /= np.abs(R) + 1e-12
    cc = np.fft.irfft(R, nfft)
    cc = np.abs(np.concatenate((cc[-maxs:], cc[: maxs + 1])))
    i = int(np.argmax(cc))
    sharp = float(cc[i] / (np.median(cc) + 1e-12))
    # second peak outside +-20 ms
    m = cc.copy(); m[max(0, i - 320): i + 320] = 0
    ratio = float(cc[i] / (m.max() + 1e-12))
    frac = 0.0
    if 0 < i < len(cc) - 1:
        y0, y1, y2 = cc[i - 1], cc[i], cc[i + 1]
        den = y0 - 2 * y1 + y2
        frac = 0.5 * (y0 - y2) / den if den else 0.0
    return (i - maxs + frac) / SR, sharp, ratio


def main(part, coarse, W=10, STEP=10, MAXS=6.0, t_from=0.0, t_to=None, tag=""):
    plaud = load_f("plaud_16k.wav")
    x = load_f(f"{part}_16k.wav")
    dur = len(x) / SR
    W = int(W); t_to = min(t_to or dur - W, dur - W)
    maxs = int(MAXS * SR)
    pts = []
    for t0 in np.arange(t_from, t_to, STEP):
        a0 = int(t0 * SR); seg = x[a0: a0 + W * SR]
        rms = float(np.sqrt((seg.astype(np.float64) ** 2).mean()))
        p0 = int(round((t0 + coarse) * SR)) - maxs
        if p0 < 0 or p0 + len(seg) + 2 * maxs > len(plaud) or rms < 3e-4:
            pts.append({"t": float(t0), "off": None, "rms": rms}); continue
        ref = plaud[p0: p0 + len(seg) + 2 * maxs]
        q = np.zeros(len(ref), dtype=np.float32); q[maxs: maxs + len(seg)] = seg
        d, sharp, ratio = gcc(ref, q, maxs)
        pts.append({"t": float(t0), "off": float(coarse + d), "sharp": sharp, "ratio": ratio, "rms": rms})
    json.dump({"part": part, "coarse": coarse, "W": W, "STEP": STEP, "MAXS": MAXS, "pts": pts},
              open(f"{ROOT}/align/dense_{part}{tag}.json", "w"), indent=0)
    # run-length summary of reliable points (ratio>1.5)
    runs = []
    for p in pts:
        ok = p["off"] is not None and p["ratio"] > 1.5 and p["sharp"] > 15
        if not ok:
            continue
        if runs and abs(runs[-1]["off"] - p["off"]) < 0.03:
            runs[-1]["t1"] = p["t"]; runs[-1]["n"] += 1
        else:
            runs.append({"t0": p["t"], "t1": p["t"], "off": p["off"], "n": 1})
    for r in runs:
        print(f"{part} t {r['t0']:7.0f}-{r['t1']:7.0f}  n={r['n']:3d}  off={r['off']:.3f}")


if __name__ == "__main__":
    part = sys.argv[1]
    if sys.argv[2] == "auto":
        coarse = float(json.load(open(f"{ROOT}/align/xcorr_result.json", encoding="utf-8"))[part]["coarse_offset_s"])
    else:
        coarse = float(sys.argv[2])
    kw = {}
    for a in sys.argv[3:]:
        k, v = a.split("="); kw[k] = v if k == "tag" else float(v)
    main(part, coarse, **kw)
