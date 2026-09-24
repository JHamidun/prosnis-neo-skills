"""Stage 1 (v2): one all-GPU decode per chunk of the 4K source produces
  (a) chunks/<tag>_<i>.mp4  — 960x540 @2 fps + 36 px black strip with SOURCE timecode, mono audio (for Gemini video)
  (b) frames/<tag>/t_<sssss.s>.jpg — 1280x720 every 2 s (for the dense frame pass)
plus audio/<tag>.wav (16 kHz mono) and silences_<tag>.json.
Parallel chunk processes (decode is the bottleneck, NVDEC is not saturated by one process).
Skip-if-done everywhere; BELOW_NORMAL priority.
Sources = the parts of job.json (vision tags P1..Pn or sources[].tag); chunk count = ceil(duration / --chunk-s).
usage: python vision_chunks.py --job job.json [parallel=4] [--chunk-s 800]
"""
import glob
import json
import math
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

CHUNK_S = 800.0  # reference webinar: 2358.8 s -> 3 chunks, 4728.7 s -> 6 chunks
if "--chunk-s" in sys.argv:
    _i = sys.argv.index("--chunk-s"); CHUNK_S = float(sys.argv[_i + 1]); del sys.argv[_i:_i + 2]
import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
ROOT = f"{J.root}/vision"
TMP = J.tmp
for k in ("TEMP", "TMP", "TMPDIR"):
    os.environ[k] = TMP

TAGS = J.vision_tags()  # {"P1": "part1", "P2": "part2"}
SOURCES = {tag: J.src(sid) for tag, sid in TAGS.items()}
DUR = {tag: J.dur(sid) for tag, sid in TAGS.items()}
NCHUNK = {tag: max(1, math.ceil(DUR[tag] / CHUNK_S)) for tag in TAGS}
LOW = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0


def chunks():
    out = []
    for tag in TAGS:
        n = NCHUNK[tag]
        step = math.ceil(DUR[tag] / n)
        for i in range(n):
            s = i * step
            e = min(DUR[tag], (i + 1) * step)
            out.append((tag, i, s, e))
    return out


def do_chunk(c):
    tag, i, s, e = c
    name = f"{tag}_{i:02d}"
    mp4 = f"{ROOT}/chunks/{name}.mp4"
    fdir = f"{ROOT}/frames/{tag}/{name}"
    done = f"{fdir}/_done"
    if os.path.exists(mp4) and os.path.exists(done):
        print(name, "skip", flush=True)
        return
    os.makedirs(f"{ROOT}/chunks", exist_ok=True)
    os.makedirs(fdir, exist_ok=True)
    for f in glob.glob(f"{fdir}/*.jpg"):
        os.remove(f)
    dt = e - s
    use_gpu = (i % 2 == 0)
    head = ("[0:v]scale_cuda=1280:720,fps=2,hwdownload,format=nv12,split[a][b];" if use_gpu
            else "[0:v]fps=2,scale=1280:720:flags=bicubic,split[a][b];")
    fc = (head +
          "[a]scale=960:540,pad=960:576:0:36:black,"
          "drawtext=fontfile='C\\:/Windows/Fonts/consola.ttf':"
          f"text='{tag} %{{pts\\:hms\\:{s}}}':x=10:y=6:fontsize=24:fontcolor=white[v];"
          "[b]select='not(mod(n\\,4))'[f]")
    dec = (["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if use_gpu else ["-threads", "8"])
    cmd = ["ffmpeg", "-y", "-v", "error", *dec,
           "-ss", str(s), "-t", str(dt), "-i", SOURCES[tag], "-filter_complex", fc,
           "-map", "[v]", "-map", "0:a", "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "30", "-g", "20",
           "-c:a", "aac", "-ac", "1", "-b:a", "48k", mp4 + ".part.mp4",
           "-map", "[f]", "-fps_mode", "passthrough", "-q:v", "3", "-start_number", "0",
           f"{fdir}/n_%05d.jpg"]
    p = subprocess.run(cmd, capture_output=True, creationflags=LOW)
    if p.returncode != 0:
        print(name, "FAILED", p.stderr.decode("utf-8", "replace")[-1500:], flush=True)
        return
    os.replace(mp4 + ".part.mp4", mp4)
    # rename frames by source time
    for f in sorted(glob.glob(f"{fdir}/n_*.jpg")):
        n = int(os.path.basename(f)[2:7])
        t = s + n * 2.0
        os.replace(f, f"{fdir}/t_{t:07.1f}.jpg")
    open(done, "w").write("ok")
    print(name, "done", flush=True)


def audio(tag):
    os.makedirs(f"{ROOT}/audio", exist_ok=True)
    wav = f"{ROOT}/audio/{tag}.wav"
    if not os.path.exists(wav):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", SOURCES[tag], "-vn", "-ac", "1", "-ar", "16000",
                        wav + ".part.wav"], check=True, creationflags=LOW)
        os.replace(wav + ".part.wav", wav)
    out = f"{ROOT}/silences_{tag}.json"
    if os.path.exists(out):
        return
    res = {}
    for noise, d in (("-40dB", 3), ("-32dB", 5)):
        p = subprocess.run(["ffmpeg", "-v", "info", "-i", wav, "-af", f"silencedetect=noise={noise}:d={d}",
                            "-f", "null", "-"], capture_output=True, creationflags=LOW)
        err = p.stderr.decode("utf-8", "replace")
        items, start = [], None
        for line in err.splitlines():
            m = re.search(r"silence_start: (-?[\d.]+)", line)
            if m:
                start = max(0.0, float(m.group(1)))
            m = re.search(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", line)
            if m and start is not None:
                items.append({"start": round(start, 2), "end": round(float(m.group(1)), 2),
                              "dur": round(float(m.group(2)), 2)})
                start = None
        if start is not None:
            items.append({"start": round(start, 2), "end": DUR[tag], "dur": round(DUR[tag] - start, 2)})
        res[f"{noise}_d{d}"] = items
    json.dump({"source": tag, **res}, open(out, "w", encoding="utf-8"), indent=1)
    print(tag, "silences", {k: len(v) for k, v in res.items()}, flush=True)


if __name__ == "__main__":
    par = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    with ThreadPoolExecutor(2) as ex:
        a = [ex.submit(audio, t) for t in TAGS]
    with ThreadPoolExecutor(par) as ex:
        list(ex.map(do_chunk, chunks()))
    print("ALL DONE", flush=True)
