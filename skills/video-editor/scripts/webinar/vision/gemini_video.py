"""Stage 2: Gemini 3.8 Flash watches ~13-min chunks of each source and returns a shot log.

Chunks are cut from the 5 fps proxy, re-encoded at 2 fps with a black strip on top that
carries the SOURCE timecode, so the model reads absolute source time from the picture.
Checkpoint: raw_v2/<chunk>.json (skip-if-done). v2: beats, thinking HIGH, media_resolution HIGH, video-slide list.
Chunks come from sources/vision_chunks.py (same --chunk-s); the slide list from vision/deck_titles.json (deck_titles.py).
Model timecodes drift +-20-35 s even with the burned-in timecode (G-V1): build_scenes.py warps them by slide anchors.
usage: python gemini_video.py --job job.json [P1 | P1_00 ...] [--chunk-s 800]
"""
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

CHUNK_S = 800.0
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
client = J.gemini()
from google.genai import types  # noqa: E402

MODEL = J.get("vision.model", "gemini-3.8-flash")

TAGS = J.vision_tags()
DUR = {tag: J.dur(sid) for tag, sid in TAGS.items()}
NCHUNK = {tag: max(1, math.ceil(DUR[tag] / CHUNK_S)) for tag in TAGS}
LAYOUTS = ["slides_share", "demo_screen", "speaker_cam_full", "speaker_cam_small_with_share",
           "gallery", "drum_raffle", "waiting_screen", "other"]


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


def fmt(t):
    t = int(round(t))
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def deck_block():
    d = json.load(open(f"{ROOT}/deck_titles.json", encoding="utf-8"))
    lines = []
    for s in d:
        extra = " / ".join(x[:70] for x in (s.get("text") or [])[:2])
        lines.append(f"{s['n']}. {s['title']}" + (f" — {extra}" if extra else ""))
    return "\n".join(lines)


PROMPT = """Ты — монтажёр-ассистент. Перед тобой фрагмент записи {event}.
Запись разбита на части. Это часть {tag}, фрагмент {idx} исходника, время исходника от {start} до {end}.

ВАЖНО ПРО ВРЕМЯ: сверху кадра чёрная полоса с таймкодом вида «{tag} HH:MM:SS.mmm» — это ТОЧНОЕ
время исходного файла. Все таймкоды в ответе давай именно по этой полосе (формат HH:MM:SS),
а не по времени от начала фрагмента. Полоса — служебная, в содержание кадра её не включай.

{people}

Слайды презентации (номер. заголовок — первые строки):
{deck}

Сделай ТОЧНЫЙ покадровый журнал монтажа этого фрагмента. Верни ТОЛЬКО JSON такого вида:
{{
 "segments": [
  {{"src_in": "HH:MM:SS", "src_out": "HH:MM:SS",
    "layout": "одно из: slides_share | demo_screen | speaker_cam_full | speaker_cam_small_with_share | gallery | drum_raffle | waiting_screen | other",
    "share_kind": "slides | demo | none",
    "slide_number": число из списка выше или null,
    "slide_title": "заголовок слайда из списка или null",
    "what_happens": "1–2 предложения по-русски: что на экране и что говорят",
    "speaker": "{speaker_enum}",
    "energy": 1-5,
    "speaker_visible": true/false,
    "cam_tile": "none | top-right | right-strip | full | other — где видно лицо спикера",
    "beats": [{{"t": "HH:MM:SS", "note": "что происходит в этот момент внутри сегмента: старт/конец ролика на слайде, читает чат, шутка, вопрос залу, передача слова, переключение окна"}}]
  }}
 ],
 "highlights": [{{"t_in": "HH:MM:SS", "t_out": "HH:MM:SS", "type": "reveal | laugh | demo_success | drum_spin | strong_phrase | audience_interaction | other", "description": "по-русски", "quote": "точная сильная фраза, если есть"}}],
 "problems": [{{"t_in": "HH:MM:SS", "t_out": "HH:MM:SS", "type": "dead_air | tech_glitch | waiting_screen | accidental_window | long_silence | audio_issue | fumble | off_topic | other", "description": "по-русски", "trim_candidate": true/false}}],
 "sensitive": [{{"t_in": "HH:MM:SS", "t_out": "HH:MM:SS", "type": "telegram_chat_list | email | phone | token_or_key | crm_customer_data | private_message | participant_full_name | other", "description": "что именно видно", "region": "где в кадре"}}]
}}

Правила layout:
- slides_share — на экране слайд презентации, окна камеры НЕ видно;
- speaker_cam_small_with_share — показ экрана (слайд ИЛИ демо) + маленькое окно камеры спикера; укажи share_kind и, если слайд, его номер;
- demo_screen — браузер/терминал/приложение/видео-ролик на весь экран без окна камеры;
- speaker_cam_full — камера спикера на весь кадр; gallery — сетка из нескольких камер;
- drum_raffle — экран розыгрыша/барабана; waiting_screen — заставка ожидания/«скоро начнём»; other — остальное.
Правила сегментов: новый сегмент при КАЖДОЙ смене слайда, смене окна/приложения, смене раскладки.
Сегменты идут встык, без пропусков, от {start} до {end}. Номер слайда сверяй по заголовку на экране;
если на слайде проигрывается встроенный ролик — так и напиши в what_happens.
energy: 1 — пауза/тишина/техника, 3 — обычный рассказ, 5 — пик (раскрытие, смех, вау-демо, барабан).
highlights — только по-настоящему сильные моменты (раскрытие ответа квиза, смех, удачное демо, сильная фраза, вращение барабана).
problems — мёртвый эфир, технические сбои, заставки ожидания, случайно показанные окна, долгие паузы, запинки/поиски окна.
sensitive — КАЖДЫЙ момент, где на экране видны: список чатов Telegram, email-адреса, телефоны, API-ключи/токены,
данные клиентов в CRM, личная переписка, полные имена участников (имя+фамилия) в плитках Zoom. Лучше перестраховаться.
Слайды со ВСТРОЕННЫМ видео (ролик играет внутри слайда, это НЕ живое демо): {video_slides}.
Если же на экране живое приложение/браузер/игра/терминал без рамки слайда (например, ведущий переключился из презентации
в браузер) — это share_kind=demo, slide_number=null, отдельный сегмент, и в what_happens напиши, какое окно показано.
beats — 0–6 заметных моментов внутри сегмента (для длинных сегментов обязательно), с таймкодами по полосе.
Не выдумывай: если не уверен в номере слайда — null."""

# job.json vision.*: event (who/what/when in one line), people (who speaks and how they look, what happens at the end),
# speaker_enum, video_slides (deck slides with an EMBEDDED video: it is not a live demo)
PROMPT_KW = dict(
    event=J.get("vision.event") or f"вебинара «{J.get('title', '')}»",
    people=J.get("vision.people") or "Кто говорит: ведущий (его камера обычно маленьким окном справа сверху) и со-ведущие.",
    speaker_enum=J.get("vision.speaker_enum") or "ведущий | со-ведущий | участник | несколько | никто",
    video_slides=", ".join(str(x) for x in J.get("deck.video_slides", [])) or "нет",
)


def make_chunk(tag, idx, s, e):
    os.makedirs(f"{ROOT}/chunks", exist_ok=True)
    out = f"{ROOT}/chunks/{tag}_{idx:02d}.mp4"
    if os.path.exists(out) and os.path.getsize(out) > 100000:
        return out
    for _ in range(360):  # wait up to 60 min for prep_chunks.py
        time.sleep(10)
        if os.path.exists(out) and os.path.getsize(out) > 100000:
            return out
    raise FileNotFoundError(f"chunk not prepared: {out} (run sources/vision_chunks.py)")
    dt = e - s
    vf = ("fps=2,pad=960:576:0:36:black,"
          "drawtext=fontfile='C\\:/Windows/Fonts/consola.ttf':"
          f"text='{tag} %{{pts\\:hms\\:{s}}}':x=10:y=6:fontsize=24:fontcolor=white")
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(s), "-t", str(dt),
           "-i", f"{ROOT}/proxy_{tag}.mp4", "-vf", vf,
           "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "30", "-g", "20",
           "-c:a", "aac", "-ac", "1", "-b:a", "48k", out + ".part.mp4"]
    subprocess.run(cmd, check=True, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    os.replace(out + ".part.mp4", out)
    return out


def upload(path):
    f = client.files.upload(file=path, config={"mime_type": "video/mp4",
                                               "display_name": os.path.basename(path)})
    for _ in range(120):
        f = client.files.get(name=f.name)
        st = str(f.state)
        if "ACTIVE" in st:
            return f
        if "FAILED" in st:
            raise RuntimeError(f"file processing failed: {f}")
        time.sleep(5)
    raise TimeoutError("file never became ACTIVE")


def parse_json(txt):
    txt = txt.strip()
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(txt)


def run_chunk(c):
    tag, idx, s, e = c
    raw = f"{ROOT}/raw_v2/{tag}_{idx:02d}.json"
    if os.path.exists(raw):
        try:
            json.load(open(raw, encoding="utf-8"))["result"]
            print(tag, idx, "skip (done)", flush=True)
            return
        except Exception:
            pass
    path = make_chunk(tag, idx, s, e)
    f = upload(path)
    prompt = PROMPT.format(tag=tag, idx=idx, start=fmt(s), end=fmt(e), deck=deck_block(), **PROMPT_KW)
    last_err = None
    for attempt in range(4):
        try:
            t0 = time.time()
            resp = client.models.generate_content(
                model=MODEL,
                contents=[types.Part.from_uri(file_uri=f.uri, mime_type="video/mp4"), prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                    max_output_tokens=65536,
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                    thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH),
                ),
            )
            txt = resp.text
            data = parse_json(txt)
            usage = resp.usage_metadata.model_dump() if resp.usage_metadata else None
            os.makedirs(f"{ROOT}/raw_v2", exist_ok=True)
            json.dump({"tag": tag, "idx": idx, "start": s, "end": e, "model": MODEL,
                       "file_uri": f.uri, "elapsed": round(time.time() - t0, 1),
                       "usage": usage, "result": data},
                      open(raw, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(tag, idx, "OK segs", len(data.get("segments", [])), "t", round(time.time() - t0),
                  flush=True)
            return
        except Exception as ex:  # retry on transient / JSON errors
            last_err = ex
            print(tag, idx, "attempt", attempt, "failed:", repr(ex)[:300], flush=True)
            try:
                open(f"{ROOT}/raw_v2/{tag}_{idx:02d}.err.txt", "w", encoding="utf-8").write(
                    repr(ex) + "\n\n" + (txt if 'txt' in dir() else ""))
            except Exception:
                pass
            time.sleep(20 * (attempt + 1))
    print(tag, idx, "GAVE UP", repr(last_err)[:300], flush=True)


if __name__ == "__main__":
    os.makedirs(f"{ROOT}/raw_v2", exist_ok=True)
    sel = sys.argv[1:]
    cs = [c for c in chunks() if not sel or f"{c[0]}_{c[1]:02d}" in sel or c[0] in sel]
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(run_chunk, cs))
    print("ALL DONE", flush=True)
