"""Fine GCC-PHAT at the part junctions (short windows) to locate exact first/last usable
samples and any start transient. usage: python junction.py --job job.json
Windows: align/align_config.json -> "junction": {"<part>_head": [t_from, t_to, coarse], "<part>_tail": [...]}
(reference run: part1_head [0, 20, 3643.70], part1_tail [2338.0, 2357.2, 3641.03], part2_head [0, 12, 6008.30],
part2_tail [4712.0, 4727.1, 6005.42]); without config: head [0, 20] and tail [dur-20.8, dur-1.55] of every part,
coarse offset = OffMap (dense scan) at the window.
Output: align/junction.json + printed table."""
import json
import numpy as np
import soundfile as sf
from scipy import signal
from dense import gcc

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
R = J.root
SR = 16000
SOS = signal.butter(4, [200, 5000], btype="band", fs=SR, output="sos")


def rd(name, a, b):
    x, _ = sf.read(f"{R}/audio/{name}", start=int(a * SR), stop=int(b * SR), dtype="float32")
    return signal.sosfilt(SOS, x).astype(np.float32)


def scan(part, t_from, t_to, coarse, W=1.5, STEP=0.25, MAXS=3.0):
    x = rd(f"{part}_16k.wav", t_from, t_to + W)
    pl_a = t_from + coarse - MAXS - 1
    pl = rd("plaud_16k.wav", pl_a, t_to + coarse + W + MAXS + 1)
    maxs = int(MAXS * SR); out = []
    for t0 in np.arange(t_from, t_to, STEP):
        a0 = int((t0 - t_from) * SR); seg = x[a0: a0 + int(W * SR)]
        if len(seg) < int(W * SR):
            break
        rms = float(np.sqrt((seg.astype(np.float64) ** 2).mean()))
        p0 = int(round((t0 + coarse - pl_a) * SR)) - maxs
        ref = pl[p0: p0 + len(seg) + 2 * maxs]
        q = np.zeros(len(ref), np.float32); q[maxs: maxs + len(seg)] = seg
        d, sharp, ratio = gcc(ref, q, maxs)
        out.append({"t": round(float(t0), 3), "off": round(float(coarse + d), 4), "sharp": round(float(sharp), 1),
                    "ratio": round(float(ratio), 2), "rms": round(rms, 5)})
    return out


def main():
    cfg = J.data("align/align_config.json", {}).get("junction")
    if not cfg:
        from offmap import OffMap
        cfg = {}
        for part in J.parts():
            m, dur = OffMap(part), J.dur(part)
            cfg[f"{part}_head"] = [0.0, 20.0, round(float(m(10.0)), 2)]
            cfg[f"{part}_tail"] = [round(dur - 20.8, 1), round(dur - 1.55, 1), round(float(m(dur - 10.0)), 2)]
    res = {k: scan(k.rsplit("_", 1)[0], float(a), float(b), float(c)) for k, (a, b, c) in cfg.items()}
    json.dump(res, open(f"{R}/align/junction.json", "w"), indent=0)
    for k, v in res.items():
        print("==", k)
        for p in v:
            flag = "OK " if p["ratio"] > 1.5 and p["sharp"] > 12 else "-- "
            print(f"  {flag} t={p['t']:8.2f} off={p['off']:10.4f} sharp={p['sharp']:6.1f} ratio={p['ratio']:5.2f} rms={p['rms']:.4f}")


if __name__ == "__main__":
    main()
