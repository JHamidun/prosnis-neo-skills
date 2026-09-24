"""S14: text materials of the FINAL video (timecodes of the edited timeline).

Inputs:  materials/final_timemap.json (build_final_timemap.py)
         materials/pdf_templates/data/transcript.data.json (build_transcript_data.py --timemap … --final)
         materials/text_build/summary.tpl.txt, rutube_desc.tpl.txt (hand-written texts; {TIMECODES}, {DURATION_HUMAN}
         are filled here)
Outputs: materials/transcript_clean.md, timecodes.txt, summary.md, rutube_meta.json (+ text_build/…report.json)
Checks:  chapter times of the transcript == chapter cards of the video; the first RuTube timecode is 00:00;
         title <= 100 chars; lint: contacts, sums and your wording rules (materials.rules); links only from the allowed list.
RuTube chapters: MM:SS below one hour, H:MM:SS after; the description is kept under ~4000 chars (upload limit, check
the report).

job.json "materials":
  {"rutube": {"title": "…", "tags": ["…"], "category": "Обучение"},
   "allowed_links": ["https://t.me/<bot>", ...],             exact links allowed in texts (the rest -> placeholders)
   "rules": [["regex", "message", ["summary", "transcript"]], ...]}   your wording rules, ADDED to the generic defaults
                                                             below; scope omitted = "summary" (summary.md + RuTube texts)
usage: python make_text_materials.py --job job.json
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
MAT = Path(J.p('materials'))
TB = MAT / 'text_build'
M = J.get('materials', {}) or {}
RT = M.get('rutube', {}) or {}
TITLE = RT.get('title') or J.get('title', '')
TAGS = RT.get('tags', [])
# Lint rules (regex, message, scopes). Scopes: 'summary' = hand-written texts (summary.md, RuTube title and
# description), 'transcript' = transcript_clean.md (spoken words stay as said: only rules that must hold there too).
# Generic defaults = contacts and sums. The owner's own wording rules (forbidden claims, product naming, topics kept
# out of public texts) live in job.json materials.rules and are ADDED to these.
RULE_MONEY = 'сумма в рублях (не цена продукта?)'
DEFAULT_RULES = [
    (r'[\w.+-]+@[\w-]+\.[\w.]+', 'e-mail', ('summary', 'transcript')),
    (r'(?<!\d)(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)', 'телефон', ('summary', 'transcript')),
    (r'\d[\d\s]*(?:₽|руб)', RULE_MONEY, ('summary',)),
]


def job_rule(r):
    """job.json rule [regex, message] or [regex, message, scope | [scopes]] -> (regex, message, scopes)."""
    sc = r[2] if len(r) > 2 else None
    return r[0], r[1], (sc,) if isinstance(sc, str) else tuple(sc or ('summary',))


RULES = DEFAULT_RULES + [job_rule(r) for r in M.get('rules', []) or []]
ALLOWED = set(M.get('allowed_links', []) or [])


def tc_short(t):
    """RuTube style: MM:SS below one hour, H:MM:SS after."""
    t = int(round(t))
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


def hms(t):
    t = int(t)
    return f'{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}'


def duration_human(sec):
    sec = int(round(sec))
    h, m = sec // 3600, sec % 3600 // 60
    return f'{h} ч {m} мин' if h else f'{m} мин'


def chapters_lines(tm):
    return [f'{tc_short(c["final_start_s"])} {c["title"]}' for c in tm['chapters']]


def transcript_md(tr, tm):
    doc = tr['doc']
    spk = tr.get('speakers') or doc.get('speakers') or {}
    short = {k: v.get('short') or v.get('name') for k, v in spk.items()}
    chs = {c['n']: c for c in tr['chapters']}
    L = [f"# {doc.get('title', '')}{': ' + doc['subtitle'] if doc.get('subtitle') else ''} — транскрипт эфира", '',
         f"{doc.get('eyebrow', '')} · запись {hms(round(tm['duration_s']))}", '']
    people = [f"{v['name']} — {v.get('role', '')}".rstrip(' —') for k, v in spk.items() if k not in ('video', 'guest')]
    if people:
        L += ['**Спикеры.** ' + '. '.join(people) + '. Имена участников из чата — только по имени.', '']
    teaser = tm.get('teaser_s') or (tm['segments'][0]['edit_in'] if tm.get('segments') else 0)
    L += ['**Таймкоды** [чч:мм:сс] — время в итоговой записи эфира: по ним можно перейти к нужному месту в видео. '
          f'Первые {int(round(teaser))} секунд записи — нарезка лучших моментов, их текст стоит ниже на своих местах.', '',
          '**О тексте.** Расшифровка автоматическая, вычитана: убраны междометия, слова-паразиты и повторы, '
          'исправлены явные ошибки распознавания; формулировки спикеров сохранены, ничего не дописано. '
          'Фамилии и контакты участников не приводятся.', '', '## Содержание', '',
          f"- [00:00:00] {tm['chapters'][0]['title'] if tm['chapters'] and not tm['chapters'][0].get('card_n') else 'Лучшее из эфира'} (нарезка)"]
    for c in tr['chapters']:
        L.append(f'- [{c["tc"]}] {c["n"]}. {c["title"]}')
    cur = None
    for p in tr['paragraphs']:
        if p['chapter'] != cur:
            cur = p['chapter']
            c = chs[cur]
            L += ['', f'## {c["n"]}. {c["title"]} [{c["tc"]}]']
            if c.get('lead'):
                L += ['', f'*{c["lead"]}*']
        L.append('')
        if p['kind'] == 'video':
            label = p['label'] or 'ролик из презентации'
            L.append(f'[{p["tc"]}] *Фрагмент видео: {label}.*')
            if p['text']:
                L += ['', f'> {p["text"]}']
        else:
            L.append(f'[{p["tc"]}] **{short.get(p["speaker"], "Участник")}:** {p["text"]}')
    L.append('')
    return '\n'.join(L)


def lint(name, text, scope='summary', allow=(), links=True):
    warns = []
    for rx, msg, scopes in RULES:
        if scope not in scopes or msg in allow:
            continue
        for mm in re.finditer(rx, text):
            warns.append(f'{name}: {msg}: …{text[max(0, mm.start() - 50): mm.end() + 30]}…'.replace('\n', ' '))
    for mm in re.finditer(r'https?://[^\s)\]]+', text) if links else ():
        if mm.group(0) not in ALLOWED:
            warns.append(f'{name}: ссылка вне списка: {mm.group(0)}')
    return warns


def main():
    tm = json.loads((MAT / 'final_timemap.json').read_text(encoding='utf-8'))
    tr = json.loads((MAT / 'pdf_templates/data/transcript.data.json').read_text(encoding='utf-8'))
    if tr['meta']['timecodes'] != 'final':
        sys.exit('transcript.data.json has provisional timecodes: run build_transcript_data.py --timemap … --final')
    edl_p = Path(J.p('edl/edl.json'))
    if abs(edl_p.stat().st_mtime - tm['edl_mtime']) > 1:
        sys.exit('edl/edl.json changed after final_timemap.json: run rebuild_all.py')
    cards = [c for c in tm['chapters'] if c.get('card_n')]
    assert [hms(round(c['final_start_s'])) for c in cards] == [c['tc'] for c in tr['chapters']], 'chapter tc mismatch'
    lines = chapters_lines(tm)
    assert lines[0].startswith('00:00 '), 'RuTube needs the first timecode at 00:00'
    tc_block = '\n'.join(lines)
    (MAT / 'timecodes.txt').write_text(tc_block + '\n', encoding='utf-8', newline='\n')
    md = transcript_md(tr, tm)
    (MAT / 'transcript_clean.md').write_text(md, encoding='utf-8', newline='\n')
    summ = (TB / 'summary.tpl.txt').read_text(encoding='utf-8')
    summ = summ.replace('{TIMECODES}', '\n'.join(f'- {x}' for x in lines)).replace('{DURATION_HUMAN}', duration_human(tm['duration_s']))
    (MAT / 'summary.md').write_text(summ, encoding='utf-8', newline='\n')
    desc = (TB / 'rutube_desc.tpl.txt').read_text(encoding='utf-8').replace('{TIMECODES}', tc_block).strip()
    meta = {'title': TITLE, 'description': desc, 'tags': TAGS, 'category': RT.get('category', 'Обучение'),
            'placeholders': sorted(set(re.findall(r'\{[A-Z_]+\}', desc))), 'duration': hms(round(tm['duration_s'])),
            'source': {'edl': str(edl_p), 'edl_mtime': edl_p.stat().st_mtime, 'chapters': J.p('edl/chapters.json')}}
    assert len(TITLE) <= 100, len(TITLE)
    with open(MAT / 'rutube_meta.json', 'w', encoding='utf-8', newline='\n') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    warns = lint('summary.md', summ, allow=(RULE_MONEY,)) + lint('rutube_meta.description', desc) + lint('rutube_meta.title', TITLE)
    # transcript: spoken words stay as said; only rules scoped to 'transcript' (contacts, forbidden claims), no link check
    warns += lint('transcript_clean.md', md, 'transcript', links=False)
    report = {'title_len': len(TITLE), 'description_len': len(desc), 'tags': len(TAGS), 'timecodes': len(lines),
              'transcript_md_chars': len(md), 'transcript_paragraphs': len(tr['paragraphs']), 'summary_md_chars': len(summ),
              'placeholders': meta['placeholders'], 'lint': warns}
    if len(desc) > 4000:
        report['lint'].append(f'description {len(desc)} chars > 4000 (RuTube)')
    TB.mkdir(parents=True, exist_ok=True)
    with open(TB / 'make_text_materials.report.json', 'w', encoding='utf-8', newline='\n') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
