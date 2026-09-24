"""Deepgram nova-3 ru transcription of an audio slice.
usage: python dg.py <src_audio> <start_s> <end_s> <out_json>
Word times in the output are shifted to be relative to the SOURCE file (start_s added).
usage: python dg.py --job job.json <src_audio> <start_s> <end_s> <out_json>   (DEEPGRAM_API_KEY from env / env_file)"""
import os, sys, json, subprocess, requests

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()


def load_env():
    J.load_env()


def main(src, a, b, out):
    load_env()
    key = os.getenv("DEEPGRAM_API_KEY")
    tmp = f"{J.tmp}/dg_slice.flac"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(a), "-to", str(b), "-i", src,
                    "-ac", "1", "-ar", "16000", "-c:a", "flac", tmp], check=True)
    r = requests.post("https://api.deepgram.com/v1/listen",
                      params={"model": "nova-3", "language": "ru", "diarize": "true", "punctuate": "true",
                              "smart_format": "true", "utterances": "true", "paragraphs": "true"},
                      headers={"Authorization": f"Token {key}", "Content-Type": "audio/flac"},
                      data=open(tmp, "rb").read(), timeout=1800)
    r.raise_for_status()
    j = r.json()
    a = float(a)
    alt = j["results"]["channels"][0]["alternatives"][0]
    for w in alt.get("words", []):
        w["start"] = round(w["start"] + a, 3); w["end"] = round(w["end"] + a, 3)
    for u in j["results"].get("utterances", []):
        u["start"] = round(u["start"] + a, 3); u["end"] = round(u["end"] + a, 3)
        for w in u.get("words", []):
            w["start"] = round(w["start"] + a, 3); w["end"] = round(w["end"] + a, 3)
    j["slice"] = {"source": src, "start_s": a, "end_s": float(b), "times": "relative to source file"}
    json.dump(j, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for u in j["results"].get("utterances", []):
        print(f"{u['start']:8.2f}-{u['end']:8.2f} S{u['speaker']}: {u['transcript']}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
