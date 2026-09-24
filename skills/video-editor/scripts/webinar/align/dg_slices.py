"""Deepgram nova-3 ru on Plaud slices (word timestamps), skip-if-done.
Word/utterance times are shifted to PLAUD time (seconds from plaud file start).
usage: python dg_slices.py --job job.json [name ...]   -> runs every slice in SLICES (or the named ones)
Slices: align/align_config.json -> "dg_slices": {name: [start_s, end_s]} in recorder seconds. Reference run: pre-show
(pre_2400_2950, intro_3075_3650), the gap between the parts (gap_5990_6016), the tail, and six verification windows
v_p<k>_<t> at the mapped times of part points (see verify_listen.py). Keyterms: job.json transcript.keyterms.
Output: align/dg_plaud/<name>.json"""
import json, os, subprocess, sys, pathlib, concurrent.futures as cf
import requests

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
R = pathlib.Path(J.root)
OUT = R / "align" / "dg_plaud"
OUT.mkdir(parents=True, exist_ok=True)
TMP = R / "tmp"
KEY = J.key("DEEPGRAM_API_KEY")
KEYTERMS = J.get("transcript.keyterms", [])
REF_SRC = J.src(J.ref_id())  # original recorder file (e.g. the Plaud .ogg)
SLICES = {k: tuple(v) for k, v in J.data("align/align_config.json", {}).get("dg_slices", {}).items()}


def run(name):
    a, b = SLICES[name]
    out = OUT / f"{name}.json"
    if out.exists() and out.stat().st_size > 500:
        return name, "skip"
    flac = TMP / f"dg_{name}.flac"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
                    "-i", REF_SRC, "-ac", "1", "-ar", "16000", "-c:a", "flac", str(flac)],
                   check=True)
    params = [("model", "nova-3"), ("language", "ru"), ("smart_format", "true"), ("punctuate", "true"),
              ("diarize", "true"), ("utterances", "true"), ("paragraphs", "true"), ("numerals", "true")]
    params += [("keyterm", k) for k in KEYTERMS]
    r = requests.post("https://api.deepgram.com/v1/listen", params=params,
                      headers={"Authorization": f"Token {KEY}", "Content-Type": "audio/flac"},
                      data=flac.read_bytes(), timeout=900)
    if r.status_code != 200:
        return name, f"HTTP {r.status_code} {r.text[:300]}"
    j = r.json()
    alt = j["results"]["channels"][0]["alternatives"][0]
    for w in alt.get("words", []):
        w["start"] = round(w["start"] + a, 3); w["end"] = round(w["end"] + a, 3)
    for u in j["results"].get("utterances", []):
        u["start"] = round(u["start"] + a, 3); u["end"] = round(u["end"] + a, 3)
        for w in u.get("words", []):
            w["start"] = round(w["start"] + a, 3); w["end"] = round(w["end"] + a, 3)
    j["slice"] = {"source": REF_SRC, "start_s": a, "end_s": b, "times": "plaud seconds"}
    out.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    flac.unlink(missing_ok=True)
    return name, f"ok words={len(alt.get('words', []))}"


if __name__ == "__main__":
    names = sys.argv[1:] or list(SLICES)
    with cf.ThreadPoolExecutor(5) as ex:
        for n, msg in ex.map(run, names):
            print(n, msg, flush=True)
