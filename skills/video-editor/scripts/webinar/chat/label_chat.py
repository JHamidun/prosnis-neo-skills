"""S5: DRAFT of chat/chat_labels.json by a model + deterministic poll-burst detection.

In the reference run every label was set by hand (indices in the builder). Here a model drafts them and a human
edits the draft; build_chat.py / build_stats.py read only chat/chat_labels.json, never the draft.

1. Poll bursts (deterministic): >= MIN_BURST short answers (<= 14 chars, e.g. «+», «2», «К», «56») within
   WINDOW_S of each other = a chat poll candidate. It is confirmed only if the host asked for it: a phrase
   like «напишите в чат / плюс / цифру / букву» in the transcript within ASK_BEFORE_S before the first answer
   (chat clock -> reference clock by job.json chat.clock_offset_s; transcript words of the parts must exist).
2. Model pass (Gemini, JSON): per message kind (question / joke / kudos / reaction / other / answer_to_poll),
   hide suggestions with a reason (privacy, off-topic, owner rules from job.json chat.rules[]), highlight notes,
   shown first names. Batches of 120 messages with 10 of overlap context; skip-if-done per batch.
3. Output chat/chat_labels.draft.json (+ chat/label_raw/*.json). Never overwrites chat_labels.json.

usage: python label_chat.py --job job.json [--no-model]
"""
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
OUT = J.p('chat')
RAWD = os.path.join(OUT, 'label_raw')
os.makedirs(RAWD, exist_ok=True)
MODEL = J.get('chat.label_model', J.get('vision.model', 'gemini-3.8-flash'))
MIN_BURST, WINDOW_S, ASK_BEFORE_S, SHORT = 5, 45, 90, 14
ASK_RX = re.compile(r'напишите|напиши|в чат|плюс|плюсик|цифр|букв|write in (the )?chat|type', re.I)
BATCH, OVERLAP = 120, 10
NO_MODEL = '--no-model' in sys.argv


def sec(t):
    h, m, s = t.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def messages():
    saved = J.data('chat/raw_parsed.json', [])
    ms = [dict(idx=i, time_msk=m['time_msk'], frm=m['frm'], text=m['text']) for i, m in enumerate(saved)]
    p = os.path.join(OUT, 'extra_messages.json')
    if os.path.exists(p):
        ms += [dict(idx=x['src_idx'], time_msk=x['time_msk'], frm=x['frm'], text=x['text']) for x in json.load(open(p, encoding='utf-8'))]
    ms.sort(key=lambda m: sec(m['time_msk']))
    return ms


def host_words():
    """[(reference wall-clock seconds, word)] of every part (transcript/<part>.words.json)"""
    tl = J.data('timeline.json', {})
    ref = J.get('align.t0_wall') or J.source(J.ref_id()).get('t0_wall')
    if not ref or not tl:
        return []
    d = datetime.fromisoformat(ref)
    t0 = d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6
    out = []
    for p in J.parts():
        f = J.p(f'transcript/{p}.words.json')
        if not os.path.exists(f):
            continue
        base = t0 + tl['offsets'][p]['start_in_plaud']
        for w in json.load(open(f, encoding='utf-8'))['words']:
            out.append((base + w['start'], w['punctuated_word']))
    out.sort()
    return out


def bursts(ms, words):
    off = float(J.get('chat.clock_offset_s', J.get('align.chat_clock_offset_s', 0.0)) or 0.0)
    team = set(J.get('chat.team_names', []) or [])
    short = [m for m in ms if len(m['text'].strip()) <= SHORT and m['frm'] not in team]
    groups, cur = [], []
    for m in short:
        if cur and sec(m['time_msk']) - sec(cur[-1]['time_msk']) > WINDOW_S:
            groups.append(cur)
            cur = []
        cur.append(m)
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        if len({m['frm'] for m in g}) < MIN_BURST:
            continue
        t_first = sec(g[0]['time_msk']) - off
        asked = [w for tt, w in words if t_first - ASK_BEFORE_S <= tt <= t_first + 5 and ASK_RX.search(w)]
        ctx = ' '.join(w for tt, w in words if t_first - ASK_BEFORE_S <= tt <= t_first + 5)
        out.append({'poll_id': f'poll_{g[0]["time_msk"].replace(":", "")}', 'ids': [m['idx'] for m in g],
                    'first': g[0]['time_msk'], 'last': g[-1]['time_msk'], 'n_authors': len({m['frm'] for m in g}),
                    'answers': sorted({m['text'].strip() for m in g})[:20], 'host_asked': bool(asked),
                    'host_context': ctx[-400:]})
    return out


PROMPT = """You label a live webinar chat (Zoom) for a video edit. For EVERY message below return one object.
Rules:
- kind: one of question | joke | kudos | reaction | answer_to_poll | other. answer_to_poll = a short answer to a
  question the host asked the audience (a digit, a letter, «+», a year, one word). reaction = only emoji/«ахах».
- hide: true when the message must NOT be shown: personal data (surnames, phones, e-mails, @handles, addresses),
  a link-only message, tech complaints about sound/lag, off-topic, a greeting to a named participant, unclear out of
  context, a duplicate of the same author's previous message, negative claims about third-party companies, and
  anything that breaks these owner rules: {rules}. Give hide_reason (short, English).
- highlight: true for the best 5-8 % (funny, strong, a story, a quote the host reacted to); highlight_note = 4-8
  Russian words why.
- name: the FIRST NAME to show for the author (from the Zoom display name); «Участник» for e-mails, nicknames,
  devices, company accounts or unclear names. Never a surname.
Return JSON: {{"items": [{{"idx": <idx>, "kind": "...", "hide": bool, "hide_reason": "...", "highlight": bool,
"highlight_note": "...", "name": "..."}}]}}
Messages (idx | time | author | text):
{msgs}
"""


def model_pass(ms):
    if NO_MODEL:
        return {}
    from google.genai import types
    client = J.gemini()
    rules = '; '.join(J.get('chat.rules', []) or []) or 'none'
    res = {}
    for b0 in range(0, len(ms), BATCH):
        f = os.path.join(RAWD, f'batch_{b0:04d}.json')
        if not os.path.exists(f):
            chunk = ms[max(0, b0 - OVERLAP):b0 + BATCH]
            lines = '\n'.join(f"{m['idx']} | {m['time_msk']} | {m['frm']} | {m['text'].replace(chr(10), ' / ')[:400]}" for m in chunk)
            for attempt in range(4):
                try:
                    r = client.models.generate_content(
                        model=MODEL, contents=[PROMPT.format(rules=rules, msgs=lines)],
                        config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0.2))
                    data = json.loads(r.text)
                    with open(f, 'w', encoding='utf-8', newline='\n') as fh:
                        json.dump(data, fh, ensure_ascii=False, indent=1)
                    break
                except Exception as e:  # network / 429 / bad JSON: back off and retry
                    print('batch', b0, 'attempt', attempt, 'error', str(e)[:200])
                    time.sleep(10 * (attempt + 1))
            else:
                raise SystemExit(f'model pass failed on batch {b0}')
        for it in json.load(open(f, encoding='utf-8')).get('items', []):
            res[str(it['idx'])] = it
    return res


def main():
    ms = messages()
    words = host_words()
    bs = bursts(ms, words)
    lab = model_pass(ms)
    draft = {'_note': 'DRAFT by label_chat.py - check every poll against the transcript, every hide/highlight by eye, '
                      'then save as chat_labels.json (see build_chat.py / build_stats.py for the schema)',
             'team': {n: {'display': f'{n.split()[0]} · команда', 'id': 'team_' + re.sub(r'\W', '', n.split()[0].lower())}
                      for n in (J.get('chat.team_names', []) or [])},
             'names': {}, 'polls': {}, 'kinds': {}, 'hide': [], 'highlight': {}, 'poll_candidates': bs}
    for b in bs:
        if b['host_asked']:
            draft['polls'][b['poll_id']] = b['ids']
    hide = {}
    for m in ms:
        it = lab.get(str(m['idx']))
        if not it:
            continue
        if it.get('name') and m['frm'] not in draft['names']:
            draft['names'][m['frm']] = it['name']
        k = it.get('kind')
        if k and k != 'answer_to_poll':
            draft['kinds'].setdefault(k, []).append(m['idx'])
        if it.get('hide'):
            hide.setdefault(it.get('hide_reason') or 'model: hide', []).append(m['idx'])
        if it.get('highlight') and not it.get('hide'):
            draft['highlight'][str(m['idx'])] = it.get('highlight_note') or ''
    draft['hide'] = [{'reason': r, 'ids': ids} for r, ids in hide.items()]
    with open(os.path.join(OUT, 'chat_labels.draft.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(draft, f, ensure_ascii=False, indent=1)
    print('messages', len(ms), 'poll candidates', len(bs), 'confirmed by host words', sum(b['host_asked'] for b in bs),
          'labelled', len(lab), 'hide', sum(len(h['ids']) for h in draft['hide']), 'highlight', len(draft['highlight']))


if __name__ == '__main__':
    main()
