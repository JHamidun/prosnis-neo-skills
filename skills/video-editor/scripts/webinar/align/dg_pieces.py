"""Deepgram nova-3 ru on the CLEANED Plaud pieces (exactly the audio that goes into the montage).
Two passes per piece (main: smart_format+numerals; plain: no smart_format, for spelling small numbers),
same params as transcript/dg_transcribe.py. Skip-if-done. Times = seconds from the start of the piece wav.
Outputs: audio/<piece>_16k.wav, transcript/raw/<piece>.deepgram.json, transcript/raw/<piece>.deepgram.plain.json
Pieces = keys of align/align_config.json "pieces" (cut and cleaned by process_recorder.py).
usage: python dg_pieces.py --job job.json"""
import os, subprocess, pathlib, requests, sys
import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
R = pathlib.Path(J.root)
KEY = J.key("DEEPGRAM_API_KEY")
KEYTERMS = J.get("transcript.keyterms", [])
PIECES = list(J.data("align/align_config.json", {}).get("pieces", {}))
(R / "transcript" / "raw").mkdir(parents=True, exist_ok=True)


def run(piece):
    wav16 = R / "audio" / f"{piece}_16k.wav"
    if not wav16.exists():
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(R / "audio" / f"{piece}.wav"),
                        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav16)], check=True)
    flac = R / "tmp" / f"{piece}_dg.flac"
    for tag, extra in (("", [("smart_format", "true"), ("numerals", "true")]),
                       (".plain", [("smart_format", "false"), ("numerals", "false")])):
        out = R / "transcript" / "raw" / f"{piece}.deepgram{tag}.json"
        if out.exists() and out.stat().st_size > 500:
            print(piece, tag or "main", "skip"); continue
        if not flac.exists():
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav16), "-c:a", "flac", str(flac)], check=True)
        params = [("model", "nova-3"), ("language", "ru"), ("punctuate", "true"), ("diarize", "true"),
                  ("utterances", "true"), ("paragraphs", "true")] + extra + [("keyterm", k) for k in KEYTERMS]
        r = requests.post("https://api.deepgram.com/v1/listen", params=params,
                          headers={"Authorization": f"Token {KEY}", "Content-Type": "audio/flac"},
                          data=flac.read_bytes(), timeout=900)
        if r.status_code != 200:
            print(piece, tag, "HTTP", r.status_code, r.text[:300]); sys.exit(1)
        out.write_text(r.text, encoding="utf-8")
        print(piece, tag or "main", "ok", len(r.json()["results"]["channels"][0]["alternatives"][0]["words"]), "words")
    flac.unlink(missing_ok=True)


if __name__ == "__main__":
    for p in PIECES:
        run(p)
