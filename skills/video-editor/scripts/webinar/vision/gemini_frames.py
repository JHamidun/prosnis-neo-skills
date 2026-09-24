"""Stage 3: dense frame pass (every 2 s from the 4K source, 1280x720), deduped to visual states.

Each unique visual state is classified by Gemini 3.8 Flash in batches: layout, slide number,
camera tile box, face box, sensitive content. Checkpoint: frames_raw/<tag>_<batch>.json.
This pass is the TRUTH for layout and slide number (the video pass mislabels live demos as slides, G-V2).
usage: python gemini_frames.py --job job.json [P1 P2]
"""
import glob
import io
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image
import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
ROOT = f"{J.root}/vision"
TMP = J.tmp
for k in ("TEMP", "TMP", "TMPDIR"):
    os.environ[k] = TMP
client = J.gemini()
from google.genai import types  # noqa: E402

MODEL = J.get("vision.model", "gemini-3.8-flash")
SOURCES = {tag: J.src(sid) for tag, sid in J.vision_tags().items()}
HOST = J.get("vision.host_label") or "ведущего"
EVENT = J.get("vision.event") or f"вебинара «{J.get('title', '')}»"
STEP = 2.0
BATCH = 24


def extract(tag):
    """Frames are produced by prep_chunks.py (frames/<tag>/<chunk>/t_<sec>.jpg)."""
    dirs = sorted(glob.glob(f"{ROOT}/frames/{tag}/{tag}_*"))
    missing = [d for d in dirs if not os.path.exists(f"{d}/_done")]
    if not dirs or missing:
        raise RuntimeError(f"frames not ready for {tag}: {missing or 'none'}")
    return dirs


def dedupe(tag):
    """Group consecutive near-identical frames into visual states."""
    out = f"{ROOT}/frames/{tag}_states.json"
    if os.path.exists(out):
        return json.load(open(out, encoding="utf-8"))
    files = sorted(glob.glob(f"{ROOT}/frames/{tag}/{tag}_*/t_*.jpg"),
                   key=lambda f: float(os.path.basename(f)[2:-4]))
    states, last_small, last_t = [], None, -1e9
    for f in files:
        t = float(os.path.basename(f)[2:-4])
        im = Image.open(f).convert("L").resize((96, 54), Image.BILINEAR)
        small = np.asarray(im, dtype=np.float32)
        if last_small is None:
            diff = 999.0
        else:
            diff = float(np.abs(small - last_small).mean())
        if diff > 2.5 or (t - last_t) >= 20:
            states.append({"t": t, "t_end": t + STEP, "file": f, "diff": round(diff, 2)})
            last_small, last_t = small, t
        else:
            states[-1]["t_end"] = t + STEP
    json.dump(states, open(out, "w", encoding="utf-8"), indent=0)
    print(tag, "frames", len(files), "states", len(states), flush=True)
    return states


def fmt(t):
    t = int(round(t))
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def deck_block():
    d = json.load(open(f"{ROOT}/deck_titles.json", encoding="utf-8"))
    return "\n".join(f"{s['n']}. {s['title']}" for s in d)


PROMPT = """Ниже кадры из записи {event}, часть {tag}.
Перед каждым кадром — метка «КАДР k | {tag} HH:MM:SS» (время исходника). Разрешение кадра 1280x720.

Слайды презентации (номер. заголовок):
{deck}

Для КАЖДОГО кадра верни объект. Ответ — ТОЛЬКО JSON: {{"frames": [ ... ]}}, где элемент:
{{"k": номер кадра,
  "layout": "slides_share | demo_screen | speaker_cam_full | speaker_cam_small_with_share | gallery | drum_raffle | waiting_screen | other",
  "share_kind": "slides | demo | none",
  "slide_number": номер слайда из списка или null,
  "screen_desc": "коротко по-русски, что на экране (для демо: какое приложение/сайт/окно)",
  "cam_tile_box": [ymin, xmin, ymax, xmax] окна камеры {host} в координатах 0–1000 или null,
  "face_box": [ymin, xmin, ymax, xmax] лица ведущего 0–1000 или null,
  "other_tiles": число других видимых окон участников,
  "sensitive": [{{"type": "telegram_chat_list | email | phone | token_or_key | crm_customer_data | private_message | participant_full_name | other",
                 "what": "что именно видно (не переписывай сами секреты полностью)",
                 "box": [ymin, xmin, ymax, xmax]}}]
}}
Правила layout: slides_share — слайд без окна камеры; speaker_cam_small_with_share — показ экрана (слайд или демо) + окно(а) камеры;
demo_screen — браузер/терминал/приложение без окна камеры; speaker_cam_full — камера на весь кадр; gallery — сетка камер;
drum_raffle — экран розыгрыша/барабана; waiting_screen — заставка ожидания.
sensitive: список чатов Telegram (имена, превью сообщений), email, телефоны, API-ключи/токены, данные клиентов в CRM/админках
(ФИО, телефоны, почты в таблицах), личная переписка, полные имена (имя+фамилия) участников в плитках Zoom.
Имена вымышленных/демо-персонажей на слайдах (например, «Юникорн», «Катя» в переписке с ботом на слайде) отмечай как
private_message только если там видны реальные контакты или ФИО. Если ничего нет — пустой список. Не выдумывай."""


def run_batch(job):
    tag, bi, items = job
    raw = f"{ROOT}/frames_raw/{tag}_{bi:03d}.json"
    if os.path.exists(raw):
        try:
            json.load(open(raw, encoding="utf-8"))["result"]["frames"]
            return
        except Exception:
            pass
    parts = [PROMPT.format(tag=tag, deck=deck_block(), event=EVENT, host=HOST)]
    for k, st in enumerate(items):
        parts.append(f"КАДР {k} | {tag} {fmt(st['t'])}")
        data = open(st["file"], "rb").read()
        parts.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
    for attempt in range(4):
        try:
            t0 = time.time()
            resp = client.models.generate_content(
                model=MODEL, contents=parts,
                config=types.GenerateContentConfig(response_mime_type="application/json",
                                                   temperature=0.1, max_output_tokens=32768))
            txt = resp.text.strip()
            if txt.startswith("```"):
                txt = txt.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(txt)
            assert len(data["frames"]) >= len(items) * 0.8, "too few frames returned"
            json.dump({"tag": tag, "batch": bi,
                       "items": [{"k": k, "t": st["t"], "t_end": st["t_end"], "file": st["file"]}
                                 for k, st in enumerate(items)],
                       "usage": resp.usage_metadata.model_dump() if resp.usage_metadata else None,
                       "result": data}, open(raw, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
            print(tag, bi, "OK", len(data["frames"]), round(time.time() - t0), "s", flush=True)
            return
        except Exception as ex:
            print(tag, bi, "attempt", attempt, repr(ex)[:200], flush=True)
            time.sleep(15 * (attempt + 1))
    print(tag, bi, "GAVE UP", flush=True)


if __name__ == "__main__":
    os.makedirs(f"{ROOT}/frames_raw", exist_ok=True)
    tags = [a for a in sys.argv[1:] if a in SOURCES] or list(SOURCES)
    jobs = []
    for tag in tags:
        extract(tag)
        states = dedupe(tag)
        for bi in range(0, len(states), BATCH):
            jobs.append((tag, bi // BATCH, states[bi:bi + BATCH]))
    print("batches", len(jobs), flush=True)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(run_batch, jobs))
    print("ALL DONE", flush=True)
