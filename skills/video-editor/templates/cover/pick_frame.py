"""Pick the strongest frame of the speaker for the cover, in two Gemini rounds (checkpoints round1.json / round2.json).

Round 1: candidates every 1 s over the span where the speaker is BIG on screen (scenes.json: a full-camera segment;
in a Zoom webinar it is often the only one) -> face crops -> Gemini ranks the top 6 with reasons.
Round 2: +-0.5 s around each pick at 0.1 s, keep the 2 sharpest frames per pick (Laplacian variance of the face box),
Gemini chooses the final frame + a backup and scores all 1-10.
The rubric: eyes open and to camera, alive friendly expression (not mid-word, no grimace), head straight, hands and mic
clear of the face, no motion blur - "an expert who is interested".

cover.json: {"pick": {"src": "<video>", "t0": 4671.6, "t1": 4709.3, "crop": [0.30, 0.10, 0.78, 1.00],
                      "face": [0.4545, 0.25, 0.6205, 0.6935], "speaker": "<Имя Фамилия>"}}   crop/face = fractions
Keys: GOOGLE_API_KEY from the environment (GEMINI_API_KEY is popped: it conflicts in the SDK).
usage: python pick_frame.py [--config cover.json]      -> cand/, dense/, round1.json, round2.json in this folder
"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
from PIL import Image

HERE = Path(__file__).resolve().parent
CFG = json.loads(Path(sys.argv[sys.argv.index('--config') + 1] if '--config' in sys.argv else HERE / 'cover.json').read_text(encoding='utf-8'))
P = CFG['pick']
os.environ.pop('GEMINI_API_KEY', None)
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

MODEL = P.get('model', 'gemini-3.8-flash')
client = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
SRC, T0, T1 = P['src'], float(P['t0']), float(P['t1'])
CROP = tuple(P.get('crop', (0.30, 0.10, 0.78, 1.00)))   # generous crop around the face incl. shoulders
FACE = tuple(P.get('face', (0.4545, 0.25, 0.6205, 0.6935)))

RUBRIC = f"""Ты фоторедактор. Выбираешь кадр спикера ({P.get('speaker', 'ведущий')}) для обложки записи вебинара
на RuTube и сайте. Кадр будет вырезан по контуру и поставлен на тёмный брендовый фон, лицо ~40% высоты обложки.
Критерии (по важности):
1) глаза открыты, взгляд в камеру (или почти в камеру), без моргания и полуприкрытых век;
2) уверенное, живое, дружелюбное выражение: лёгкая улыбка или собранное вовлечённое лицо; рот закрыт
   или естественная улыбка — НЕ посреди слова с перекошенным ртом, НЕ гримаса;
3) голова прямо, не опущена, не сильно повёрнута; руки не перекрывают лицо; микрофон не закрывает рот;
4) резкость: без смаза движения.
Будь строг: из похожих кадров выбирай тот, где выражение лица лучше всего продаёт «эксперт, которому интересно»."""


def face_crop(path, width=640):
    im = Image.open(path).convert('RGB')
    W, H = im.size
    x0, y0, x1, y1 = CROP
    im = im.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
    return im.resize((width, int(im.height * width / im.width)), Image.LANCZOS)


def jpeg_part(im, q=88):
    b = io.BytesIO()
    im.save(b, 'JPEG', quality=q)
    return types.Part.from_bytes(data=b.getvalue(), mime_type='image/jpeg')


def sharpness(path):
    g = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    H, W = g.shape
    x0, y0, x1, y1 = FACE
    return float(cv2.Laplacian(g[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)], cv2.CV_64F).var())


def ask(items, instruction, schema_hint, width):
    parts = [RUBRIC + '\n\n' + instruction + '\n\nОтвет строго JSON: ' + schema_hint]
    for label, path in items:
        parts.append(f'Кадр {label}:')
        parts.append(jpeg_part(face_crop(path, width)))
    r = client.models.generate_content(model=MODEL, contents=parts,
                                       config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0.2))
    return json.loads(r.text)


def extract(t, out):
    if not Path(out).exists():
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', f'{t:.2f}', '-i', SRC, '-frames:v', '1', '-q:v', '1', '-y', str(out)], check=True)
    return out


def main():
    (HERE / 'cand').mkdir(exist_ok=True)
    r1_path = HERE / 'round1.json'
    if r1_path.exists():
        r1 = json.loads(r1_path.read_text(encoding='utf-8'))
    else:
        items = []
        t = int(T0) + 1
        while t <= T1:
            items.append((str(t), extract(t, HERE / f'cand/c_{t}.jpg')))
            t += 1
        r1 = ask(items, f'Перед тобой {len(items)} кадров, подпись = секунда исходника. Выбери 6 лучших '
                        'по убыванию качества и коротко (по-русски) объясни каждый.',
                 '{"top": [{"frame": "<подпись>", "why": "..."}], "rejected_common_reasons": "..."}', 480)
        r1_path.write_text(json.dumps(r1, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    print('round1:', json.dumps(r1, ensure_ascii=False, indent=1))
    r2_path = HERE / 'round2.json'
    if r2_path.exists():
        print('round2:', r2_path.read_text(encoding='utf-8'))
        return
    (HERE / 'dense').mkdir(exist_ok=True)
    pool = []
    for item in r1['top'][:6]:
        base = float(item['frame'])
        local = []
        for k in range(-5, 6):
            t = round(base + k * 0.1, 2)
            if T0 <= t <= T1:
                p = extract(t, HERE / f'dense/t_{t:08.2f}.jpg')
                local.append((sharpness(p), t, p))
        local.sort(reverse=True)
        pool += local[:2]  # two sharpest frames around each round-1 pick
        print(f'  around {base}: sharpest ' + ', '.join(f'{t:.2f}={s:.0f}' for s, t, _ in local[:3]))
    pool.sort(key=lambda x: x[1])
    r2 = ask([(f'{t:.2f}', p) for _, t, p in pool],
             f'Финальный выбор из {len(pool)} кадров (подпись = секунда исходника, кадры крупнее). '
             'Выбери ОДИН лучший для обложки и запасной; оцени каждый кадр 1-10.',
             '{"best": "<подпись>", "backup": "<подпись>", "scores": {"<подпись>": <1-10>}, "why_best": "...", "expression_best": "..."}', 900)
    r2['sharpness'] = {f'{t:.2f}': round(s) for s, t, _ in pool}
    r2_path.write_text(json.dumps(r2, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    print('round2:', json.dumps(r2, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
