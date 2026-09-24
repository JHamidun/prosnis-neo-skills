"""Transcribe webinar parts with Deepgram nova-3 (REST, not the SDK: SDK 6 broke the old API - gotcha G-T5).
Two passes per part (skip-if-done checkpoint on raw JSON):
  main  : smart_format + numerals + punctuate + diarize + utterances + paragraphs + keyterms -> raw/<part>.deepgram.json
  plain : same audio, smart_format=false numerals=false -> raw/<part>.deepgram.plain.json (build_outputs spells small
          numbers from it: live speech says "один", smart_format writes "1" - G-T6)
Audio: audio/<part>_tr16k.ogg (mono 16 kHz opus, made here from the source if missing) + _tr16k.wav (for tighten()).
Keyterms: job.json transcript.keyterms (product names, speakers, places - the words Deepgram mangles).
usage: python dg_transcribe.py --job job.json [part ...]"""
import json, os, sys, time, pathlib, subprocess, concurrent.futures as cf
import requests

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
KEY = J.key("DEEPGRAM_API_KEY")

BASE = pathlib.Path(J.root)
RAW = BASE / "transcript" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
(BASE / "audio").mkdir(parents=True, exist_ok=True)

KEYTERMS = J.get("transcript.keyterms", [])
LANG = J.get("transcript.language", "ru")


def prep_audio(part: str):
    ogg, wav = BASE / "audio" / f"{part}_tr16k.ogg", BASE / "audio" / f"{part}_tr16k.wav"
    if not wav.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", J.src(part), "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", str(wav)], check=True)
    if not ogg.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "libopus", "-b:a", "48k", str(ogg)], check=True)
    return ogg


def run(part: str, use_keyterms: bool = True, plain: bool = False):
    out = RAW / f"{part}.deepgram{'.plain' if plain else ''}.json"
    if out.exists() and out.stat().st_size > 1000:
        return part, f"{'plain' if plain else 'main'} skip (exists)"
    audio = prep_audio(part).read_bytes()
    params = [("model", "nova-3"), ("language", LANG), ("punctuate", "true"),
              ("diarize", "true"), ("utterances", "true"), ("paragraphs", "true")]
    params += ([("smart_format", "false"), ("numerals", "false")] if plain else [("smart_format", "true"), ("numerals", "true")])
    if use_keyterms:
        params += [("keyterm", k) for k in KEYTERMS]
    t0 = time.time()
    r = requests.post("https://api.deepgram.com/v1/listen", params=params,
                      headers={"Authorization": f"Token {KEY}", "Content-Type": "audio/ogg"},
                      data=audio, timeout=1800)
    if r.status_code != 200:
        if use_keyterms and r.status_code == 400:
            print(part, "400 with keyterms:", r.text[:300], "-> retry without", flush=True)
            return run(part, use_keyterms=False, plain=plain)
        return part, f"HTTP {r.status_code}: {r.text[:500]}"
    data = r.json()
    data.setdefault("_meta_local", {})["keyterms_used"] = use_keyterms
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    words = data["results"]["channels"][0]["alternatives"][0].get("words", [])
    return part, (f"{'plain' if plain else 'main'} ok {time.time()-t0:.0f}s words={len(words)} "
                  f"utts={len(data['results'].get('utterances', []))} keyterms={use_keyterms}")


if __name__ == "__main__":
    parts = sys.argv[1:] or J.parts()
    jobs = [(p, pl) for p in parts for pl in (False, True)]
    with cf.ThreadPoolExecutor(2) as ex:
        for part, msg in ex.map(lambda a: run(a[0], plain=a[1]), jobs):
            print(part, msg, flush=True)
