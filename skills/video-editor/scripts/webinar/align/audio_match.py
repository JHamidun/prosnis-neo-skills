"""Long-term speech spectrum of Plaud vs Zoom (PART1 proxy audio) over the SAME aligned stretch
(host speaking), -> 1/3-octave correction curve (Zoom - Plaud, dB) for a matching EQ, plus
noise-floor estimate of the Plaud intro. Output: align/audio_match.json
Windows: align/align_config.json -> "audio_match": {"part": "part1", "part_t": 20, "plaud_t": 3663.6, "dur": 600,
"noise": [3106, 54], "speech": [3165, 180]} (reference run values; noise = a quiet stretch of the recorder before the
show, speech = host speech on the recorder). usage: python audio_match.py --job job.json"""
import json, subprocess
import numpy as np
from scipy import signal

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
R = J.root
SR = 48000
REF_SRC = J.src(J.ref_id())
AM = {"part": "part1", "part_t": 20, "plaud_t": 3663.6, "dur": 600, "noise": [3106, 54], "speech": [3165, 180]}
AM.update(J.data("align/align_config.json", {}).get("audio_match", {}))


def pcm(args):
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args, "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


def speech_psd(x, keep=0.6):
    """Welch PSD over the loudest `keep` fraction of 50 ms frames (speech-dominated)."""
    fl = int(0.05 * SR); n = len(x) // fl
    fr = x[: n * fl].reshape(n, fl)
    e = (fr ** 2).mean(1)
    thr = np.quantile(e, 1 - keep)
    y = fr[e >= thr].ravel()
    f, p = signal.welch(y, SR, nperseg=8192)
    return f, p


def bands(f, p):
    centers = 1000 * 2 ** (np.arange(-14, 14) / 3.0)  # ~63 Hz .. 20 kHz
    centers = centers[(centers >= 50) & (centers <= 20000)]
    out = []
    for c in centers:
        lo, hi = c / 2 ** (1 / 6), c * 2 ** (1 / 6)
        sel = (f >= lo) & (f < hi)
        out.append(10 * np.log10(p[sel].mean() + 1e-20))
    return centers, np.array(out)


def main():
    # PART1 t=20..620 <-> plaud 3663.6..4263.6 (offset ~3643.6; spectra are long-term, ms-level sync irrelevant)
    z = pcm(["-ss", str(AM["part_t"]), "-t", str(AM["dur"]), "-i", f"{R}/proxy/{AM['part']}.mp4", "-vn"])
    pl = pcm(["-ss", str(AM["plaud_t"]), "-t", str(AM["dur"]), "-i", REF_SRC])
    fz, pz = speech_psd(z); fp, pp = speech_psd(pl)
    c, bz = bands(fz, pz); _, bp = bands(fp, pp)
    corr = bz - bp
    corr -= np.interp(1000, c, corr)  # normalise at 1 kHz (level handled by loudnorm)
    # Zoom effective bandwidth: highest band within 30 dB of the 1 kHz band level
    ref = np.interp(1000, c, bz)
    bw = float(max(ci for ci, b in zip(c, bz) if b > ref - 30))
    # noise floor of plaud intro: quiet stretch 3106-3160 (waiting, no speech)
    nz = pcm(["-ss", str(AM["noise"][0]), "-t", str(AM["noise"][1]), "-i", REF_SRC])
    nf_db = 20 * np.log10(np.sqrt((nz ** 2).mean()) + 1e-12)
    sp = pcm(["-ss", str(AM["speech"][0]), "-t", str(AM["speech"][1]), "-i", REF_SRC])
    fl = int(0.05 * SR); e = (sp[: len(sp) // fl * fl].reshape(-1, fl) ** 2).mean(1)
    sp_db = 10 * np.log10(np.quantile(e, 0.9) + 1e-20)
    res = {"centers_hz": [round(float(x), 1) for x in c], "zoom_db": [round(float(x), 2) for x in bz],
           "plaud_db": [round(float(x), 2) for x in bp], "corr_db": [round(float(x), 2) for x in corr],
           "zoom_bandwidth_hz": bw, "plaud_noise_rms_dbfs": round(float(nf_db), 1),
           "plaud_speech_p90_dbfs": round(float(sp_db), 1)}
    json.dump(res, open(f"{R}/align/audio_match.json", "w"), indent=1)
    for ci, a, b, d in zip(c, bz, bp, corr):
        print(f"{ci:8.0f} Hz  zoom {a:7.2f}  plaud {b:7.2f}  corr {d:+6.2f}")
    print("zoom bw", bw, "noise", nf_db, "speech p90", sp_db)


if __name__ == "__main__":
    main()
