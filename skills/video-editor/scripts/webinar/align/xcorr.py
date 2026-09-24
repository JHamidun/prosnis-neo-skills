"""Align PART1/PART2 Zoom audio against the Plaud room recording.

Stage 1: coarse global offset from 100 fps band-limited log-energy envelopes (FFT xcorr).
Stage 2: fine offsets every STEP seconds via GCC-PHAT on raw 16 kHz audio (+-1 s search),
         then a robust linear fit plaud_t = a + b * part_t (b captures clock drift).
Writes align/xcorr_result.json. Reference = audio/plaud_16k.wav (sources/proxies.py), parts = job align.parts.
usage: python xcorr.py --job job.json [part ...]
"""
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
HOP = 160  # 10 ms


def load(name):
    x, sr = sf.read(f"{ROOT}/audio/{name}", dtype="float32")
    assert sr == SR, (name, sr)
    return x


def envelope(x):
    sos = signal.butter(4, [250, 4000], btype="band", fs=SR, output="sos")
    y = signal.sosfilt(sos, x)
    n = len(y) // HOP
    e = np.sqrt((y[: n * HOP].reshape(n, HOP) ** 2).mean(axis=1) + 1e-10)
    e = np.log(e)
    # remove slow trend (2 s moving mean), normalise
    k = 200
    trend = np.convolve(e, np.ones(k) / k, mode="same")
    e = e - trend
    e = (e - e.mean()) / (e.std() + 1e-9)
    return e.astype(np.float32)


def fft_xcorr(ref, q):
    """corr[lag] = sum ref[lag + i] * q[i], lag >= 0 (q placed inside ref)."""
    n = len(ref) + len(q)
    nfft = 1 << int(np.ceil(np.log2(n)))
    R = np.fft.rfft(ref, nfft)
    Q = np.fft.rfft(q, nfft)
    c = np.fft.irfft(R * np.conj(Q), nfft)
    return c  # index = lag (positive), negative lags wrap to end


def gcc_phat(a, b, max_shift):
    """delay d (samples) such that a[t] ~ b[t - d]... returns shift of b relative to a."""
    n = len(a) + len(b)
    nfft = 1 << int(np.ceil(np.log2(n)))
    A = np.fft.rfft(a, nfft)
    B = np.fft.rfft(b, nfft)
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-12
    cc = np.fft.irfft(R, nfft)
    cc = np.concatenate((cc[-max_shift:], cc[: max_shift + 1]))
    i = int(np.argmax(np.abs(cc)))
    peak = cc[i]
    # sharpness: peak vs median abs
    sharp = float(np.abs(peak) / (np.median(np.abs(cc)) + 1e-12))
    # sub-sample parabolic
    if 0 < i < len(cc) - 1:
        y0, y1, y2 = np.abs(cc[i - 1]), np.abs(cc[i]), np.abs(cc[i + 1])
        den = y0 - 2 * y1 + y2
        frac = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    else:
        frac = 0.0
    return (i - max_shift) + frac, sharp, float(np.sign(peak))


def main():
    plaud = load("plaud_16k.wav")
    ep = envelope(plaud)
    out = {"plaud_frames": len(ep)}
    parts = sys.argv[1:] or J.parts()
    for part in parts:
        x = load(f"{part}_16k.wav")
        ex = envelope(x)
        c = fft_xcorr(ep, ex)
        valid = c[: len(ep) - len(ex) + 1] if len(ep) >= len(ex) else c
        # also allow part starting before plaud (negative lag) -> wrap region
        neg = c[-len(ex):]
        allc = np.concatenate((neg, valid))
        lags = np.concatenate((np.arange(-len(ex), 0), np.arange(len(valid))))
        i = int(np.argmax(allc))
        best = lags[i]
        norm = allc / len(ex)
        pk = float(norm[i])
        mask = np.abs(lags - best) > 300  # exclude +-3 s
        second = float(norm[mask].max())
        coarse_s = best * HOP / SR
        print(f"{part}: coarse offset in plaud = {coarse_s:.2f} s, peak={pk:.3f}, 2nd={second:.3f}, ratio={pk/second:.2f}")
        res = {"coarse_offset_s": coarse_s, "env_peak": pk, "env_second": second, "env_ratio": pk / second}

        # fine: GCC-PHAT windows
        sos = signal.butter(4, [200, 5000], btype="band", fs=SR, output="sos")
        W = 20 * SR
        STEP = 60
        maxs = int(1.0 * SR)
        pts = []
        dur = len(x) / SR
        for t0 in np.arange(10, dur - 25, STEP):
            a0 = int(t0 * SR)
            seg = x[a0: a0 + W]
            if np.sqrt((seg ** 2).mean()) < 1e-3:
                continue
            p0 = int(round((t0 + coarse_s) * SR)) - maxs
            if p0 < 0 or p0 + W + 2 * maxs > len(plaud):
                continue
            ref = plaud[p0: p0 + W + 2 * maxs]
            segf = signal.sosfilt(sos, seg)
            reff = signal.sosfilt(sos, ref)
            q = np.zeros(len(reff), dtype=np.float64)
            q[maxs: maxs + W] = segf
            d, sharp, sgn = gcc_phat(reff, q, maxs)
            off = coarse_s + d / SR
            pts.append({"part_t": float(t0), "plaud_t": float(t0 + off), "offset": float(off), "sharp": sharp, "sign": sgn})
        P = np.array([[p["part_t"], p["offset"], p["sharp"]] for p in pts])
        good = P[P[:, 2] > 8] if len(P) else P
        # robust linear fit (iterative trimming)
        sel = good
        for _ in range(4):
            if len(sel) < 3:
                break
            b, a = np.polyfit(sel[:, 0], sel[:, 1], 1)
            r = sel[:, 1] - (a + b * sel[:, 0])
            thr = max(3 * np.median(np.abs(r)) * 1.4826, 0.002)
            sel = sel[np.abs(r) <= thr]
        b, a = np.polyfit(sel[:, 0], sel[:, 1], 1)
        r_all = good[:, 1] - (a + b * good[:, 0])
        res.update({
            "fine_points": pts,
            "n_points": len(pts), "n_sharp": int(len(good)), "n_inliers": int(len(sel)),
            "fit_offset_at_part0_s": float(a), "fit_drift_s_per_s": float(b),
            "fit_resid_median_ms": float(np.median(np.abs(r_all)) * 1000),
            "inlier_resid_max_ms": float(np.abs(sel[:, 1] - (a + b * sel[:, 0])).max() * 1000),
            "offset_at_part_end_s": float(a + b * dur),
            "part_dur_s": dur,
        })
        print(f"  fine: {len(pts)} pts, sharp {len(good)}, inliers {len(sel)}; offset@0={a:.4f}s drift={b*1e6:.1f} ppm; "
              f"offset@end={a + b*dur:.4f}; median resid {np.median(np.abs(r_all))*1000:.1f} ms")
        out[part] = res
    try:
        prev = json.load(open(f"{ROOT}/align/xcorr_result.json", encoding="utf-8"))
    except Exception:
        prev = {}
    prev.update(out)
    json.dump(prev, open(f"{ROOT}/align/xcorr_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
