"""Cross-check the Deepgram words with faster-whisper large-v3 where Deepgram (ru) swallows or mangles names
and short terms (gotcha G-T3: "прошёл курс с, даже…" instead of "с <Имя>", "уже мало" instead of "у <Имени>",
"с помощью ⌀" instead of "с помощью ИИ").

Symptom that selects a spot: a SHORT service word ("с", "у", "и", "в", "к", "о", "а", "на", "по", "ли") or any word of
<= 3 letters that lasts anomalously long (>= --min-dur, default 0.5 s), or a token equal to a --watch word
variant. For every spot a 2-5 s clip (pauses of the Deepgram words as borders) is transcribed by faster-whisper
WITHOUT initial_prompt (a prompt with the names makes Whisper "hear" them - the vote would be rigged), words only.
Whisper is better on names and stutters, worse on punctuation and it drags timestamps over pauses: from it we take
WORDS, the timing stays Deepgram + energy (tighten) or CTC alignment. Output is a REPORT of candidates for
anchored rules in transcript/corrections.json (with the clip path as evidence) - nothing is applied here.
Disputed candidates: vote per clip with other engines (Gemini audio part "дословно, с паразитами"); when all
engines agree on something strange, keep what was said and flag it to the owner.

usage: python whisper_crosscheck.py --job job.json [part ...] [--min-dur 0.5] [--watch Имя --watch ИИ]
needs: pip install faster-whisper (CUDA float16 on the GPU, ~1 min per minute of audio on a laptop RTX 4090);
       do not run it while a GPU render is going on the same machine.
output: transcript/whisper_crosscheck.json
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load as _load_job, lower_self  # noqa: E402

J = _load_job()
SHORT = {"с", "у", "и", "в", "к", "о", "а", "на", "по", "ли", "же", "бы"}


def norm(s):
    return re.sub(r"[^а-яёa-z0-9]", "", s.lower()).replace("ё", "е")


def spots(words, min_dur, watch):
    out = []
    for i, w in enumerate(words):
        t = norm(w.get("punctuated_word", w["word"]))
        dur = w["end"] - w["start"]
        why = None
        if t in SHORT and dur >= min_dur:
            why = f"служебное «{t}» длится {dur:.2f} с"
        elif 0 < len(t) <= 3 and dur >= max(min_dur, 0.9):
            why = f"короткое «{t}» длится {dur:.2f} с"
        elif any(t.startswith(norm(x)[:4]) for x in watch if len(norm(x)) >= 4):
            why = f"слово из списка наблюдения «{t}»"
        if why:
            out.append((i, why))
    return out


def clip_bounds(words, i, lo=2.0, hi=5.0):
    """borders in pauses around word i: extend left/right to the nearest gap >= 0.15 s, total 2-5 s."""
    a, b = words[i]["start"], words[i]["end"]
    j = i
    while j > 0 and b - words[j - 1]["start"] < hi and (words[j]["start"] - words[j - 1]["end"] < 0.15 or b - a < lo):
        j -= 1
        a = words[j]["start"]
    k = i
    while k + 1 < len(words) and words[k + 1]["end"] - a < hi and (words[k + 1]["start"] - words[k]["end"] < 0.15 or b - a < lo):
        k += 1
        b = words[k]["end"]
    return max(0.0, a - 0.12), b + 0.12, j, k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parts", nargs="*")
    ap.add_argument("--min-dur", type=float, default=0.5)
    ap.add_argument("--watch", action="append", default=[])
    ap.add_argument("--model", default="large-v3")
    a = ap.parse_args()
    watch = a.watch or [J.get("speakers.host.name", "").split(" ")[0]] + J.get("transcript.watch_words", [])
    watch = [x for x in watch if x]
    lower_self()
    from faster_whisper import WhisperModel  # noqa: E402
    model = WhisperModel(a.model, device="cuda", compute_type="float16")
    R = pathlib.Path(J.root)
    clips = R / "tmp" / "whisper_xcheck"
    clips.mkdir(parents=True, exist_ok=True)
    out_p = R / "transcript" / "whisper_crosscheck.json"
    report = json.loads(out_p.read_text(encoding="utf-8")) if out_p.exists() else {}
    for part in a.parts or J.parts():
        wj = json.loads((R / "transcript" / f"{part}.words.json").read_text(encoding="utf-8"))
        words = wj["words"]
        audio = R / "audio" / f"{part}_tr16k.wav"
        res = report.setdefault(part, {})
        for i, why in spots(words, a.min_dur, watch):
            key = f"{words[i]['start']:.2f}"
            if key in res:
                continue  # skip-if-done
            s, e, j, k = clip_bounds(words, i)
            wav = clips / f"{part}_{int(s * 100)}.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", str(audio),
                            "-ac", "1", "-ar", "16000", str(wav)], check=True)
            segs, _ = model.transcribe(str(wav), language=J.get("transcript.language", "ru"), word_timestamps=True,
                                       beam_size=5, condition_on_previous_text=False)
            ww = [x.word.strip() for sg in segs for x in (sg.words or [])]
            dg = " ".join(w.get("punctuated_word", w["word"]) for w in words[j:k + 1])
            wh = " ".join(ww)
            res[key] = {"t": words[i]["start"], "why": why, "clip": [round(s, 2), round(e, 2)], "clip_file": str(wav),
                        "deepgram": dg, "whisper": wh, "differs": norm(dg) != norm(wh)}
            out_p.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            if res[key]["differs"]:
                print(f"{part} {words[i]['start']:8.2f} {why}\n   DG: {dg}\n   WH: {wh}", flush=True)
    n = sum(1 for p in report.values() for v in p.values() if v["differs"])
    print("candidates (deepgram != whisper):", n, "->", out_p)


if __name__ == "__main__":
    main()
