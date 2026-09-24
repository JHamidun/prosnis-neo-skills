"""Piecewise offset map part_t -> plaud_t built from dense GCC-PHAT scans.
offset(t) = plaud_t - part_t. Reliable points: ratio>1.5, sharp>15, then a running-median
(5 pts) outlier filter (|off - med| < 0.15 s). Interpolation: linear between kept points."""
import json
import numpy as np

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
ROOT = f"{J.root}/align"


def load_points(part):
    pts = []
    for tag in ("_full", "_head", "_tail"):
        try:
            d = json.load(open(f"{ROOT}/dense_{part}{tag}.json"))
        except FileNotFoundError:
            continue
        W = d["W"]
        for p in d["pts"]:
            if p["off"] is None or p["ratio"] <= 1.5 or p["sharp"] <= 15:
                continue
            if abs(p["off"] - d["coarse"]) > d["MAXS"] - 0.02:  # search-boundary hit = no match
                continue
            # window centre is the natural time stamp of a window measurement
            pts.append((p["t"] + W / 2.0, p["off"], tag))
    pts.sort()
    t = np.array([p[0] for p in pts]); o = np.array([p[1] for p in pts])
    keep = np.ones(len(t), bool)
    for i in range(len(t)):
        lo, hi = max(0, i - 3), min(len(t), i + 4)
        med = np.median(o[lo:hi])
        keep[i] = abs(o[i] - med) < 0.15
    return t[keep], o[keep], t[~keep], o[~keep]


class OffMap:
    def __init__(self, part):
        self.t, self.o, self.rt, self.ro = load_points(part)

    def __call__(self, part_t):
        return np.interp(part_t, self.t, self.o)

    def plaud(self, part_t):
        return np.asarray(part_t) + self(part_t)


if __name__ == "__main__":
    for part in J.parts():
        m = OffMap(part)
        print(part, "kept", len(m.t), "rejected", len(m.rt), "first", m.t[0], m.o[0], "last", m.t[-1], m.o[-1])
