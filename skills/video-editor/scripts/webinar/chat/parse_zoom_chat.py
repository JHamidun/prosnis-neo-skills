"""S5: parse BOTH Zoom chat logs into one data set (G-C3).

Zoom writes two different logs of the same chat:
  * the saved chat (meeting_saved_chat.txt / meeting_saved_new_chat.txt):
        2026-09-23 18:05:11 От <Имя> кому Все:
        \t<text, may span lines>
    (English clients: "From <Name> to Everyone:")  - all messages, NO reactions;
  * the client log (chat.txt of the recording client):
        18:45:12\t От <Имя> : <text>
    - starts when that client joined, carries reactions (EN «Reacted to "…" with 👍», RU «Реакция на "…" с помощью 👍»),
      removals («Removed a 👍 reaction from "…"», «Элемент 👍 удален из "…"») and sometimes messages the saved chat lost.

Outputs (chat/):
  raw_parsed.json        saved-chat messages in file order = ARRIVAL order [{time_msk, frm, to, text}]
  client_parsed.json     client-log messages (no reactions) [{time_msk, frm, text}]
  extra_messages.json    messages present only in the client log (append to the display list; check by eye)
  reactions_parsed.json  net reactions [{t, frm, target, trunc, emoji}] (an add cancelled by a later removal of the
                         same author/target/emoji is dropped)
  reaction_events.json   every add/remove event with sign (+1/-1)
  parse_meta.json        counts, client_log_start (reactions are known only after it)

Stamps of the saved chat are the SENDER DEVICE clock (G-C1): keep file order, smooth later (build_edl chat module).
usage: python parse_zoom_chat.py --job job.json      (job.json chat.saved_chat / chat.client_log)
"""
import json
import os
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
OUT = J.p('chat')
os.makedirs(OUT, exist_ok=True)

SAVED_HDR = re.compile(r'^(\d{4}-\d{2}-\d{2} )?(\d{2}:\d{2}:\d{2}) (?:От|From) (.+?) (?:кому|to) (.+?):$', re.M)
CLIENT_HDR = re.compile(r'^(\d{2}:\d{2}:\d{2})\t (?:От|From) (.+?) : ', re.M)
REACT_PATS = [
    # (regex, sign, which group is target / emoji / truncation flag)
    (re.compile(r'^Reacted to "(.*)" with (\S+)$', re.S), 1, 'en_q'),
    (re.compile(r'^Reacted to (.*?)\.\.\. with "(\S+)"$', re.S), 1, 'en_trunc'),
    (re.compile(r'^Реакция на "(.*?)(\.\.\.)?" с помощью (\S+)$', re.S), 1, 'ru'),
    (re.compile(r'^Removed a (\S+) reaction from "(.*)"$', re.S), -1, 'en_rm'),
    (re.compile(r'^Элемент (\S+) удален из "(.*?)(\.\.\.)?"$', re.S), -1, 'ru_rm'),
]


def norm(s):
    return re.sub(r'\s+', ' ', s).strip().rstrip('.').strip()


CLIENT_REPLY = re.compile(r'^(?:Replying to|Ответ на) "(.*?)"\n\n(.*)$', re.S)
SAVED_REPLY = re.compile(r'^(?:Ответ на|Reply to|Replying to) «(.*?)»:\n(.*)$', re.S)


def hms(t):
    h, m, s = t.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def body(text):
    """normalized message body without the reply header of either log"""
    for rx in (CLIENT_REPLY, SAVED_REPLY):
        mm = rx.match(text)
        if mm:
            text = mm.group(2)
            break
    return norm(text).lower()


def saved_style(text):
    """client-log reply header -> the saved-chat form 'Ответ на «…»:<newline><body>' (the builder parses that one)"""
    mm = CLIENT_REPLY.match(text)
    if mm:
        q = mm.group(1)
        if len(q) > 50:  # the saved chat quotes the first 50 characters + '...'
            q = q[:50] + '...'
        return f'Ответ на «{q}»:\n{mm.group(2)}'
    return text


def read(path):
    with open(path, encoding='utf-8-sig') as f:
        return f.read()


def parse_saved(raw):
    ms = list(SAVED_HDR.finditer(raw))
    out = []
    for i, m in enumerate(ms):
        body = raw[m.end():ms[i + 1].start() if i + 1 < len(ms) else len(raw)]
        lines = [ln[1:] if ln.startswith('\t') else ln for ln in body.strip('\n').split('\n')]
        out.append({'time_msk': m.group(2), 'frm': m.group(3), 'to': m.group(4), 'text': '\n'.join(lines).strip()})
    return out


def parse_client(raw):
    cms = list(CLIENT_HDR.finditer(raw))
    msgs, events = [], []
    for i, m in enumerate(cms):
        body = raw[m.end():cms[i + 1].start() if i + 1 < len(cms) else len(raw)].strip()
        t, frm = m.group(1), m.group(2)
        ev = None
        for rx, sign, kind in REACT_PATS:
            mm = rx.match(body)
            if not mm:
                continue
            g = mm.groups()
            if kind == 'en_q':
                target, emo, tr = g[0], g[1], g[0].endswith('...')
                if tr:
                    target = target[:-3]
            elif kind == 'en_trunc':
                target, emo, tr = g[0], g[1], True
            elif kind == 'ru':
                target, tr, emo = g[0], bool(g[1]), g[2]
            elif kind == 'en_rm':
                emo, target, tr = g[0], g[1], False
            else:
                emo, target, tr = g[0], g[1], bool(g[2])
            ev = {'t': t, 'frm': frm, 'target': norm(target), 'trunc': tr, 'emoji': emo, 'sign': sign}
            break
        if ev:
            events.append(ev)
        else:
            msgs.append({'time_msk': t, 'frm': frm, 'text': body})
    return msgs, events


def net_reactions(events):
    """keep an add unless a LATER removal by the same author of the same emoji on the same target cancels it"""
    out = []
    for i, e in enumerate(events):
        if e['sign'] < 0:
            continue
        cancelled = any(r['sign'] < 0 and r['frm'] == e['frm'] and r['emoji'] == e['emoji'] and
                        (r['target'].startswith(e['target'][:18]) or e['target'].startswith(r['target'][:18]))
                        for r in events[i + 1:])
        if not cancelled:
            out.append({k: e[k] for k in ('t', 'frm', 'target', 'trunc', 'emoji')})
    return out


def dump(name, data):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def main():
    saved_p = J.get('chat.saved_chat')
    client_p = J.get('chat.client_log')
    saved = parse_saved(read(J.rel(saved_p))) if saved_p else []
    cmsgs, events = parse_client(read(J.rel(client_p))) if client_p else ([], [])
    # messages only in the client log. The two logs differ for the SAME message: reply header
    # ('Replying to "…"' + blank line / 'Ответ на "…"' + blank line vs 'Ответ на «…»:'), stamps +-1-2 s, and the saved chat keeps the
    # EDITED text while the client log has the first version -> match by author, |dt| <= 8 s and a fuzzy body match
    used = set()
    extra = []
    for m in cmsgs:
        bm, tm = body(m['text']), hms(m['time_msk'])
        hit = None
        for j, s in enumerate(saved):
            if j in used or s['frm'] != m['frm'] or abs(hms(s['time_msk']) - tm) > 8:
                continue
            bs = body(s['text'])
            if bs == bm or bs.startswith(bm[:12]) or bm.startswith(bs[:12]) or SequenceMatcher(None, bs, bm).ratio() >= 0.6:
                hit = j
                break
        if hit is None:
            extra.append({'src': 'client_log', 'time_msk': m['time_msk'], 'frm': m['frm'], 'text': saved_style(m['text'])})
        else:
            used.add(hit)
    for i, x in enumerate(extra, 1):
        x['src_idx'] = f'x{i}'
    react = net_reactions(events)
    dump('raw_parsed.json', saved)
    dump('client_parsed.json', cmsgs)
    dump('extra_messages.json', extra)
    dump('reaction_events.json', events)
    dump('reactions_parsed.json', react)
    meta = {'saved_messages': len(saved), 'client_messages': len(cmsgs), 'extra_only_in_client_log': len(extra),
            'reaction_events': len(events), 'reactions_net': len(react),
            'client_log_start': (cmsgs[0]['time_msk'] if cmsgs else (events[0]['t'] if events else None)),
            'addressees': dict(Counter(m['to'] for m in saved)),
            'note': 'client_log_start: reactions/extra messages exist only after this time (earlier messages get reactions=None)'}
    dump('parse_meta.json', meta)
    print(json.dumps(meta, ensure_ascii=False))
    if any(a not in ('Все', 'Everyone') for a in meta['addressees']):
        print('WARNING: private messages in the saved chat (addressee != everyone) - never show them')


if __name__ == '__main__':
    main()
