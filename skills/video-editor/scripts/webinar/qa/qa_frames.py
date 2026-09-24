"""S13: frame QA of rendered excerpts / chunks / the final with Gemini vision.

Extracts full 1920x1080 JPEG frames every <step> seconds, sends them in ONE request with a strict checklist
(overflow, covered text, >2 subtitle lines, empty/broken frames, fallback fonts, PRIVACY, polish) and stores
<video dir>/qa/<name>.json (skip-if-done) + the frames in <video dir>/qa/<name>/.
Every "issue" is a lead, not a verdict: the model looks at ~1 frame per step and calls smooth eased moves "hard
cuts" (G-Q1) - confirm each one on the frames (contact_sheet.py, every 3rd frame) before acting.

job.json: qa.frames_context (what the programme looks like, one paragraph - default: the Program design),
          qa.model (default vision.model / gemini-3.8-flash)
usage: python qa_frames.py --job job.json <step_s> <video.mp4> [<video.mp4> ...]
As a module (qa_watch.py): qa_frames.qa(video, step) -> dict
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load, low_flags  # noqa: E402

J = load()
MODEL = J.get('qa.model', J.get('vision.model', 'gemini-3.8-flash'))
CONTEXT = J.get('qa.frames_context') or (
    'a professionally edited recording of a webinar: dark stage, the clean slide (hand-drawn sketch style) or a live demo '
    'in a rounded window, host camera window, a live chat column on the right, karaoke subtitles in a bottom band, chapter '
    'cards, name plates, poll cards, hand-drawn doodles')
_client = None

PROMPT = """You are a strict broadcast QA editor. These are consecutive frames (timestamps in the file names
listed below, in order) from {context}.
Frames: {names}

Check EVERY frame and report only real defects:
- text overflowing its box / clipped / cut words / garbled or scattered letters / wrong glyphs (tofu, serif fallback);
- any overlay (chat, camera, caption band, doodle, tag, poll, banner, confetti) covering slide text or demo UI;
- subtitles colliding with other elements or running outside the band, more than 2 lines;
- empty/black/broken frames, missing images, placeholder boxes, misaligned or half-rendered windows;
- privacy: e-mails, phone numbers, API keys/tokens, surnames of private people, browser tabs/address bars readable;
- visual polish problems (awkward crops, faces cut, stretched images, low-res upscales).
Return JSON only: {{"ok": true|false, "score_1_10": n, "issues": [{{"frame": "<file name>", "severity": "high|medium|low", "what": "...", "fix": "..."}}], "notes": "one line"}}"""


def client():
    global _client
    if _client is None:
        _client = J.gemini()
    return _client


def extract(video, step, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(video)],
                               capture_output=True, text=True).stdout.strip())
    names = []
    t = min(1.0, dur / 2)
    while t < dur - 0.1:
        name = f't{int(t // 60):02d}m{t % 60:05.2f}s.jpg'
        p = outdir / name
        if not p.exists():
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{t:.2f}', '-i', str(video), '-frames:v', '1',
                            '-q:v', '3', str(p)], **low_flags())
        if p.exists():
            names.append(p)
        t += step
    return names


def qa(video, step):
    from google.genai import types
    video = Path(video)
    qd = video.parent / 'qa'
    out = qd / f'{video.stem}.json'
    if out.exists() and out.stat().st_size > 50:
        print('cached', out)
        return json.loads(out.read_text(encoding='utf-8'))
    frames = extract(video, step, qd / video.stem)
    parts = [types.Part.from_bytes(data=p.read_bytes(), mime_type='image/jpeg') for p in frames]
    prompt = PROMPT.format(context=CONTEXT, names=', '.join(p.name for p in frames))
    for attempt in range(3):
        try:
            r = client().models.generate_content(
                model=MODEL, contents=parts + [prompt],
                config=types.GenerateContentConfig(response_mime_type='application/json', media_resolution='MEDIA_RESOLUTION_HIGH'))
            data = json.loads(r.text)
            break
        except Exception as e:  # noqa: BLE001
            print('retry', attempt, repr(e)[:300])
            time.sleep(10)
    else:
        data = {'ok': None, 'error': 'gemini failed'}
    data['frames'] = [p.name for p in frames]
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print('OK', video.name, 'ok' if data.get('ok') else 'ISSUES', data.get('score_1_10'), len(data.get('issues', [])))
    return data


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    step = float(sys.argv[1])
    for v in sys.argv[2:]:
        qa(v, step)
