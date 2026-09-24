"""Gemini re-listen of disputed spots in the cleaned recorder pieces (times = <piece>.wav seconds). Skip-if-done.
Config: align/align_config.json -> "relisten": {"spots": {"intro_plaud": [2.0, 92.0, ...]}, "prompt": "..."}
The prompt gives the model the CONTEXT of the stretch (who speaks, what is on screen, names and terms that will be
said) and asks for a verbatim transcript with fillers and [неразборчиво]; the answers are evidence for the anchored
corrections of build_recorder_words.py, never applied blindly.
usage: python relisten_pieces.py --job job.json -> transcript/raw/gemini_relisten_plaud.json"""
import json, os, pathlib, subprocess, concurrent.futures as cf
import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
client = J.gemini()
from google.genai import types  # noqa: E402
B = pathlib.Path(J.root)
CL = B / "tmp" / "relisten_plaud"; CL.mkdir(parents=True, exist_ok=True)
OUT = B / "transcript" / "raw" / "gemini_relisten_plaud.json"
_RC = J.data("align/align_config.json", {}).get("relisten", {})
SPOTS = [(piece, float(t)) for piece, ts in _RC.get("spots", {}).items() for t in ts]
PROMPT = _RC.get("prompt") or ("Это фрагмент записи русскоязычного вебинара. Запиши дословно, что звучит, включая слова-паразиты. "
                               "Если слово неразборчиво — пометь [неразборчиво]. Без комментариев, только текст.")
old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}


def job(spot):
    piece, t = spot
    k = f"{piece.replace('_plaud', '')}@{t}"
    if k in old:
        return k, old[k]
    a = max(0.0, t - 5.0)
    clip = CL / f"{piece}_{int(t*10)}.ogg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a}", "-t", "12", "-i", str(B / "audio" / f"{piece}_16k.wav"),
                    "-c:a", "libopus", "-b:a", "32k", str(clip)], check=True)
    r = client.models.generate_content(model="gemini-3.8-flash",
                                       contents=[types.Part.from_bytes(data=clip.read_bytes(), mime_type="audio/ogg"), PROMPT])
    return k, {"start": a, "end": a + 12, "text": (r.text or "").strip()}


with cf.ThreadPoolExecutor(6) as ex:
    for f in cf.as_completed([ex.submit(job, t) for t in SPOTS]):
        try:
            k, v = f.result(); old[k] = v
            OUT.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            print("ERR", repr(e)[:300])
for k in sorted(old, key=lambda s: float(s.split("@")[1])):
    print(k, f"[{old[k]['start']:.1f}-{old[k]['end']:.1f}]", "|", old[k]["text"].replace("\n", " "))
