"""Cover QA with Gemini: pairwise comparison of two versions in BOTH orders (the judge prefers the first image - position
bias, G-Q2) + a defect check of the final with the client's hard constraints (never argue with them).
A version wins only if it wins in both orders.

cover.json: {"critique": {"constraints": "<жёсткие условия заказчика одним абзацем>"}}
usage: python critique_pair.py <old.png> <new.png> [--config cover.json] [--out critique.json]
"""
import io
import json
import os
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
os.environ.pop('GEMINI_API_KEY', None)
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402


def part(path, size=(1200, 675)):
    im = Image.open(path).convert('RGB').resize(size, Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, 'PNG')
    return types.Part.from_bytes(data=b.getvalue(), mime_type='image/png')


def main():
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and not sys.argv[i - 1].startswith('--')]
    if len(pos) < 2:
        raise SystemExit(__doc__)
    old, new = pos[0], pos[1]
    cfg_p = Path(sys.argv[sys.argv.index('--config') + 1]) if '--config' in sys.argv else HERE / 'cover.json'
    cfg = json.loads(cfg_p.read_text(encoding='utf-8')) if cfg_p.exists() else {}
    constraints = (cfg.get('critique') or {}).get('constraints', '')
    client = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
    model = (cfg.get('critique') or {}).get('model', 'gemini-3.8-flash')
    res = {}
    for order in ((old, new), (new, old)):
        parts = [constraints + '\nСравни две обложки A и B. Какая профессиональнее и чище (вырезка спикера, ореолы, баланс, '
                 'читаемость)? Ответ JSON: {"winner":"A|B","why":"..."}', 'A:', part(order[0]), 'B:', part(order[1])]
        r = client.models.generate_content(model=model, contents=parts,
                                           config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0.1))
        j = json.loads(r.text)
        j['A'], j['B'] = order
        res['order_%s_first' % ('old' if order[0] == old else 'new')] = j
    wins = [res['order_old_first']['winner'] == 'B', res['order_new_first']['winner'] == 'A']
    res['new_wins_both_orders'] = all(wins)
    parts = [constraints + """\nПроверь финальную обложку (полный размер) на ДЕФЕКТЫ, которые надо исправить до публикации:
артефакты вырезки (кайма, куски фона, ступеньки контура), наложения элементов, обрезанный текст, опечатки,
элементы, закрывающие лицо или текст. Не предлагай смену концепции. Для каждого дефекта — координаты в пикселях 1200x675.
JSON: {"defects":[{"what":"...","where":"...","severity":"high|medium|low","fix":"..."}],"ready_to_publish":true|false,"score_1_10":n}""",
             part(new)]
    r = client.models.generate_content(model=model, contents=parts,
                                       config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0.1))
    res['defects'] = json.loads(r.text)
    out = Path(sys.argv[sys.argv.index('--out') + 1]) if '--out' in sys.argv else HERE / 'critique.json'
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
