"""Re-listen short unclear spots with Gemini to resolve ASR ambiguities (read-only helper; its answers are
EVIDENCE for anchored rules in corrections.json, never applied automatically). Skip-if-done per spot.
Config: transcript/relisten.json {"spots": {part: [t, ...]}, "prompt": "..."}; the prompt names the host, the
topic and the terms that will be said (reference run: ~12 s clips around 34 spots, 6 parallel requests).
usage: python gemini_relisten.py --job job.json -> transcript/raw/gemini_relisten.json"""
import json, os, pathlib, subprocess, concurrent.futures as cf

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
client = J.gemini()
from google.genai import types  # noqa: E402

BASE = pathlib.Path(J.root)
CLIPS = BASE / "tmp" / "relisten"
CLIPS.mkdir(parents=True, exist_ok=True)
OUT = BASE / "transcript" / "raw" / "gemini_relisten.json"

_RL = J.data("transcript/relisten.json", {})
SPOTS = _RL.get("spots", {})
PROMPT = _RL.get("prompt") or ("Это фрагмент записи русскоязычного вебинара. Запиши дословно, что звучит, "
                               "включая слова-паразиты. Если слово неразборчиво — пометь [неразборчиво]. Без комментариев, только текст.")

old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}


def job(part, t):
    key = f"{part}@{t}"
    if key in old:
        return key, old[key]
    a = max(0.0, t - 5.0)
    clip = CLIPS / f"{part}_{int(t*10)}.ogg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a}", "-t", "12", "-i",
                    str(BASE / "audio" / f"{part}_tr16k.wav"), "-c:a", "libopus", "-b:a", "32k", str(clip)], check=True)
    r = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[types.Part.from_bytes(data=clip.read_bytes(), mime_type="audio/ogg"), PROMPT],
    )
    return key, {"start": a, "end": a + 12, "text": (r.text or "").strip()}


with cf.ThreadPoolExecutor(6) as ex:
    futs = [ex.submit(job, p, t) for p, ts in SPOTS.items() for t in ts]
    for f in cf.as_completed(futs):
        try:
            k, v = f.result()
            old[k] = v
            OUT.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            print("ERR", repr(e)[:300])
for k in sorted(old, key=lambda s: (s.split("@")[0], float(s.split("@")[1]))):
    print(k, "|", old[k]["text"].replace("\n", " "))
