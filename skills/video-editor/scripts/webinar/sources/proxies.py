"""Launch proxy transcodes + WAV extraction detached at BELOW_NORMAL priority.
Idempotent: skips outputs that already exist and pass ffprobe duration check.
Parts (job.json align.parts) -> proxy/<id>.mp4 (1920x1080 25 fps NVENC cq20 g50, scale_cuda) + audio/<id>_16k.wav;
the reference recorder (align.reference) -> audio/plaud_16k.wav (contract name of the reference track).
usage: python proxies.py --job job.json [wav] [proxy]"""
import os, subprocess, json, sys

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
ROOT = J.root
TMP = f"{ROOT}/tmp"
env = dict(os.environ, TEMP=TMP, TMP=TMP, TMPDIR=TMP)
for _d in ("audio", "proxy", "align"):
    os.makedirs(f"{ROOT}/{_d}", exist_ok=True)

SRC = {sid: J.src(sid) for sid in J.parts()}
DUR = {sid: J.dur(sid) for sid in J.parts()}
REF = J.ref_id()

BELOW = 0x00004000
DETACHED = 0x00000008
NEWGRP = 0x00000200


def ok(path, dur):
    if not os.path.exists(path):
        return False
    try:
        d = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                           "-of", "csv=p=0", path]).decode().strip())
        return abs(d - dur) < 1.0
    except Exception:
        return False


def launch(name, args, log):
    f = open(log, "w", encoding="utf-8")
    p = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT, env=env,
                         creationflags=BELOW | DETACHED | NEWGRP)
    print(name, "pid", p.pid)


what = sys.argv[1:] or ["wav", "proxy"]
if "wav" in what:  # reference recorder track (mono 16 kHz) for xcorr / dense / junction / process_recorder
    _ref_wav = f"{ROOT}/audio/plaud_16k.wav"
    if not ok(_ref_wav, J.dur(REF)):
        launch("wav-ref", ["ffmpeg", "-y", "-hide_banner", "-i", J.src(REF), "-vn", "-ac", "1", "-ar", "16000",
                           "-c:a", "pcm_s16le", _ref_wav], f"{ROOT}/align/wav_ref.log")
for k, src in SRC.items():
    if "wav" in what:
        wav = f"{ROOT}/audio/{k}_16k.wav"
        if not ok(wav, DUR[k]):
            launch(f"wav-{k}", ["ffmpeg", "-y", "-hide_banner", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
                                "-c:a", "pcm_s16le", wav], f"{ROOT}/align/wav_{k}.log")
    if "proxy" in what:
        out = f"{ROOT}/proxy/{k}.mp4"
        if not ok(out, DUR[k]):
            launch(f"proxy-{k}", [
                "ffmpeg", "-y", "-hide_banner", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                "-i", src, "-map", "0:v:0", "-map", "0:a:0",
                "-vf", "scale_cuda=1920:1080:interp_algo=lanczos:format=nv12",
                "-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "20", "-b:v", "0",
                "-maxrate", "20M", "-bufsize", "40M", "-profile:v", "high",
                "-g", "50", "-bf", "3", "-r", "25",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", out], f"{ROOT}/align/proxy_{k}.log")
