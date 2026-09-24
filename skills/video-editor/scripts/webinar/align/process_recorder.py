"""Cut + clean the Plaud-only pieces so they sit next to the Zoom audio.
Chain: highpass 85 Hz (Zoom rolls off <90 Hz) -> tonal match EQ (from align/audio_match.json,
Zoom-minus-Plaud 1/3-oct curve, clamped +-3 dB, only 125 Hz..6.3 kHz; Plaud has no content >8 kHz so
nothing is boosted there) -> light FFT denoise (afftdn nr=10 dB, noise floor tracked) ->
+12 dB pre-gain + gentle speech compressor (3:1 @ -24 dB, Zoom-like LRA) -> ONE static gain so the
INTRO lands at -16 LUFS integrated -> sample-peak limiter at -2.2 dBFS (true peak <= -1.5 dBTP).
The gap piece gets the very same gain (same mic, same level) instead of its own normalisation.
Output 48 kHz stereo 24-bit WAV. (v1 used loudnorm, which fell back to DYNAMIC mode = pumping: process_plaud.v1.py)
v3: the chain delays audio (firequalizer FIR + alimiter lookahead: measured 38.0 ms in v2 = process_plaud.v2.py).
Now: decode with PRE s of pre-roll, process, MEASURE the lag vs plaud_16k.wav (GCC-PHAT), then cut sample-exactly
at PRE+lag so output sample 0 == plaud_in (verified by re-measuring: residual lag must be 0).
Pieces: align/align_config.json -> "pieces": {name: [plaud_in, plaud_out]} (reference run: intro_plaud
[3081.60, 3647.35] = 0.84 s before the first words .. join + 1 s handle; gap_plaud [5998.788, 6009.296] = the
8.51 s between the Zoom parts + handles). The FIRST piece defines the static gain, the others reuse it.
usage: python process_recorder.py --job job.json"""
import json, os, re, subprocess
import numpy as np
import soundfile as sf

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
R = J.root
SRC = J.src(J.ref_id())
os.environ["TEMP"] = os.environ["TMP"] = f"{R}/tmp"

PIECES = {k: tuple(v) for k, v in J.data("align/align_config.json", {}).get("pieces", {}).items()}


def eq_string():
    m = json.load(open(f"{R}/align/audio_match.json"))
    ent = []
    for c, g in zip(m["centers_hz"], m["corr_db"]):
        if 120 <= c <= 6400:
            ent.append(f"entry({c:.0f},{max(-3.0, min(3.0, g)):.2f})")
    ent = ["entry(20,0)", "entry(100,0)"] + ent + ["entry(8000,0)", "entry(24000,0)"]
    return "firequalizer=gain_entry='" + ";".join(ent) + "'"


def pre_chain():
    return (f"highpass=f=85:poles=2,{eq_string()},afftdn=nr=10:nf=-58:tn=1,volume=12dB,"
            "acompressor=threshold=-24dB:ratio=3:attack=15:release=250:knee=4:makeup=1")


def ebur(args):
    cmd = ["ffmpeg", "-hide_banner", "-nostats", *args, "-af", "ebur128=peak=true", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore").stderr
    summ = err[err.rfind("Summary:"):]

    def g(k):
        v = re.search(k + r":\s+(-?[\d.]+|-inf)", summ).group(1)
        return -120.0 if v == "-inf" else float(v)
    return {"I": g("I"), "LRA": g("LRA"), "TP": g("Peak")}


PRE, POST = 1.0, 0.5


def lag_vs_plaud(wav48, plaud_start, a, b):
    """seconds by which wav48 (sample 0 == plaud_start nominally) lags plaud_16k.wav, GCC-PHAT on [a, b]"""
    x = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a}", "-to", f"{b}", "-i", wav48, "-ac", "1", "-ar", "16000",
                        "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(x, np.float32)
    SR = 16000
    y, _ = sf.read(f"{R}/audio/plaud_16k.wav", start=int(round((plaud_start + a - 0.2) * SR)),
                   stop=int(round((plaud_start + b + 0.2) * SR)), dtype="float32")
    n = 1 << int(np.ceil(np.log2(2 * len(y))))
    X, Y = np.fft.rfft(x, n), np.fft.rfft(y, n)
    Rr = Y * np.conj(X); Rr /= np.abs(Rr) + 1e-12
    cc = np.fft.irfft(Rr, n)[:len(y)]
    k = int(np.argmax(cc))
    # parabolic sub-sample refinement
    if 0 < k < len(cc) - 1:
        y0, y1, y2 = cc[k - 1], cc[k], cc[k + 1]
        k = k + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
    return round(float(0.2 - k / SR), 5), round(float(cc.max() / cc.std()), 1)


def main():
    res = {"chain": pre_chain(), "limiter": "alimiter=limit=0.78:attack=3:release=60:level=false", "pieces": {}}
    gain = None
    for name, (a, b) in PIECES.items():
        pre = f"{R}/tmp/{name}_pre.wav"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{a - PRE:.3f}", "-to", f"{b + POST:.3f}",
                        "-i", SRC, "-af", pre_chain() + ",aresample=48000", "-ar", "48000", "-c:a", "pcm_f32le", pre],
                       check=True)
        m_pre = ebur(["-i", pre])
        if gain is None:  # derived from the intro only
            gain = -16.0 - m_pre["I"]
        long = f"{R}/tmp/{name}_long.wav"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", pre, "-af",
                        f"volume={gain:.2f}dB,alimiter=limit=0.78:attack=3:release=60:level=false",
                        "-ar", "48000", "-c:a", "pcm_f32le", long], check=True)
        w0, w1 = (PRE + 2.0, PRE + min(22.0, b - a - 0.5))  # measure on speech inside the piece
        lag, peak = lag_vs_plaud(long, a - PRE, w0, w1)
        s0 = int(round((PRE + lag) * 48000)); n = int(round((b - a) * 48000))
        out = f"{R}/audio/{name}.wav"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", long, "-af",
                        f"atrim=start_sample={s0}:end_sample={s0 + n},asetpts=N/SR/TB",
                        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", out], check=True)
        chk = [lag_vs_plaud(out, a, t0, t0 + 8.0) for t0 in ((1.0, (b - a) / 2, b - a - 9.0) if b - a > 20 else (0.5,))]
        m_out = ebur(["-i", out])
        res["pieces"][name] = {"file": out, "plaud_in": a, "plaud_out": b, "duration": round(b - a, 3),
                               "pre": m_pre, "gain_db": round(gain, 2), "out": m_out,
                               "latency_compensated_s": lag, "latency_peak": peak,
                               "residual_lag_s_check": [c[0] for c in chk], "check_peaks": [c[1] for c in chk]}
        print(name, "pre", m_pre, "gain", round(gain, 2), "lag", lag, "residual", chk, "out", m_out, flush=True)
        os.remove(pre); os.remove(long)
    json.dump(res, open(f"{R}/align/process_plaud.json", "w"), indent=1)


if __name__ == "__main__":
    main()
