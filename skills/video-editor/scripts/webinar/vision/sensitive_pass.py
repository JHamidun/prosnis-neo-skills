"""Stage 5: focused SENSITIVE pass over EVERY 2-s frame (1280x720) of both sources.

Frame pass v1 asked for too much per frame and missed browser tabs / @handles. This pass asks
only one question: what private/sensitive data is visible. Checkpoint: sens_raw/<tag>_<batch>.json.
One narrow question per frame catches browser tabs, @handles and notifications the broad pass missed (G-V3);
names SPOKEN aloud are found in the transcript (build_scenes.py sens_audio), not here.
usage: python sensitive_pass.py --job job.json [P1 P2]
"""
import glob, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
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
BATCH = 20

PROMPT = """Ты — проверяющий приватности перед публикацией записи вебинара (Zoom, демонстрация экрана ведущего).
Ниже кадры 1280x720, перед каждым метка «КАДР k | {tag} HH:MM:SS». Найди на КАЖДОМ кадре всё, что нельзя
показывать публично без размытия. Смотри ВНИМАТЕЛЬНО на мелкий текст: вкладки и адресную строку браузера,
панель закладок, всплывающие уведомления (Windows, Telegram, почта), панель задач, плитки участников Zoom
справа (подписи с именами), таблицы, списки, скриншоты переписок.

Типы:
- browser_ui — вкладки/адрес/закладки, по которым видно почту, имена людей, названия компаний-клиентов, личные сервисы, локальные пути;
- notification — всплывающее уведомление любого приложения;
- telegram_chat_list — список чатов Telegram / другого мессенджера;
- private_message — реальная переписка людей (не макет на слайде с вымышленным персонажем);
- email — адрес почты (даже частично);
- phone — номер телефона (даже частично);
- token_or_key — ключи API, токены, пароли, секреты;
- crm_customer_data — ФИО/контакты/суммы клиентов в CRM, админке, таблице;
- participant_full_name — подписи в плитках Zoom с именем и фамилией (одним пунктом на кадр, перечисли видимые имена);
- username — @никнеймы реальных людей (Telegram и т.п.);
- client_company — название компании-клиента в вкладке/документе вне слайда;
- other — другое приватное.

Для каждого пункта: "type", "text" (что видно; секреты/телефоны маскируй: первые 3 символа + ***),
"box": [ymin, xmin, ymax, xmax] в 0–1000, "on_slide": true если это часть заранее подготовленного слайда презентации
(а не живое окно), "severity": "high" (ключи, телефоны, почта, CRM-клиенты, личная переписка, уведомления с текстом),
"medium" (полные имена участников, @ники, вкладки), "low" (имена без фамилий, вымышленные/демо-данные, замаскированные значения).
Замаскированные данные вида «P***l», «+7 9** *** ** 22», «anna@example.com» (явно демо) — severity low.
Ответ — ТОЛЬКО JSON: {{"frames": [{{"k": 0, "items": [ ... ]}}, ...]}} — по объекту на КАЖДЫЙ кадр, items пустой, если ничего нет.
Не выдумывай: если текст не читается — не придумывай его."""


def fmt(t):
    t = int(round(t))
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def frames(tag):
    fs = glob.glob(f"{ROOT}/frames/{tag}/{tag}_*/t_*.jpg")
    return sorted(((float(os.path.basename(f)[2:-4]), f) for f in fs))


def run_batch(job):
    tag, bi, items = job
    raw = f"{ROOT}/sens_raw/{tag}_{bi:03d}.json"
    if os.path.exists(raw):
        try:
            json.load(open(raw, encoding="utf-8"))["result"]["frames"]
            return
        except Exception:
            pass
    parts = [PROMPT.format(tag=tag)]
    for k, (t, f) in enumerate(items):
        parts.append(f"КАДР {k} | {tag} {fmt(t)}")
        parts.append(types.Part.from_bytes(data=open(f, "rb").read(), mime_type="image/jpeg"))
    for attempt in range(5):
        try:
            t0 = time.time()
            resp = client.models.generate_content(
                model=MODEL, contents=parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.1, max_output_tokens=32768,
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH))
            txt = resp.text.strip()
            if txt.startswith("```"):
                txt = txt.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(txt)
            assert len(data["frames"]) >= len(items) * 0.9, "too few frames"
            json.dump({"tag": tag, "batch": bi, "items": [{"k": k, "t": t, "file": f} for k, (t, f) in enumerate(items)],
                       "usage": resp.usage_metadata.model_dump() if resp.usage_metadata else None,
                       "result": data}, open(raw, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
            print(tag, bi, "OK", sum(len(x.get("items") or []) for x in data["frames"]), round(time.time() - t0), "s", flush=True)
            return
        except Exception as ex:
            print(tag, bi, "attempt", attempt, repr(ex)[:200], flush=True)
            time.sleep(15 * (attempt + 1))
    print(tag, bi, "GAVE UP", flush=True)


if __name__ == "__main__":
    os.makedirs(f"{ROOT}/sens_raw", exist_ok=True)
    jobs = []
    for tag in (sys.argv[1:] or list(J.vision_tags())):
        fr = frames(tag)
        for i in range(0, len(fr), BATCH):
            jobs.append((tag, i // BATCH, fr[i:i + BATCH]))
    print("batches", len(jobs), flush=True)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(run_batch, jobs))
    print("ALL DONE", flush=True)
