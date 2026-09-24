"""S5: build chat/chat_display.json - the list the animated chat column of the Program comp is built from.

Inputs (chat/): raw_parsed.json + extra_messages.json + reactions_parsed.json (parse_zoom_chat.py),
chat_labels.json (hand-checked labels: draft from label_chat.py, then edited by a human - see the schema below),
timeline.json (part offsets on the reference track), job.json (recorder t0_wall, chat.clock_offset_s).

Privacy is the point of this stage (style.md, G-C4): first names only, e-mails / nicknames / devices / company
accounts -> «Участник»; links, e-mails and phones are cut from every text; the final self-check lists every
surname / @ / link that is still visible (chat/_build_diag.json) - it must be empty for shown messages.

chat_labels.json (all keys optional; message ids = index in raw_parsed.json, extra messages = "x1", "x2" ...):
{
  "team":   {"<Zoom name>": {"display": "Имя · команда", "id": "team_<x>"}},     host/co-hosts/moderators
  "names":  {"<Zoom name>": "<shown name>"},          overrides of the automatic first-name rule
  "polls":  {"<poll_id>": [ids]},                     answers that belong to a chat poll (build_stats.py counts them)
  "kinds":  {"other"|"reaction"|"joke"|"kudos"|"question": [ids]},
  "poll_kind_force": [ids],                           keep kind answer_to_poll although the id is also in kinds
  "hide":   [{"reason": "...", "ids": [ids]}],        never shown (reason stays in the data)
  "highlight": {"<id>": "note"},                      bigger bubble (the edit may linger on it)
  "override":  {"<id>": "text"},  "edit_note": {"<id>": "why"},
  "manual_reply": {"<id>": ["quoted text", "reply body"]},   participant pasted the quote into the first line
  "mention_fix": [["@Name\\s*", ""]],                 regex -> replacement
  "privacy_surnames": ["..."],                        extra strings the self-check must not find in shown texts
  "privacy_allow": ["..."],                           words of Zoom names that are NOT personal (a city, «Team»)
  "part_t0_msk": {"<part>": "HH:MM:SS.ss"},           optional override of the part starts on the reference clock
  "order": "time"                                     "time" (reference run: stable sort by stamp) | "file"
}
usage: python build_chat.py --job job.json
"""
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
OUT = J.p('chat') + '/'
LAB = J.data('chat/chat_labels.json', {})
TL = J.data('timeline.json')


def sec(t):
    h, m, s = t.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def ikey(k):
    return int(k) if isinstance(k, str) and k.isdigit() else k


def idmap(d):
    return {ikey(k): v for k, v in (d or {}).items()}


# ---------- clock: chat stamps -> part time ----------
# chat clock minus reference-derived wall clock: job.json chat.clock_offset_s, else the S2 estimate align.chat_clock_offset_s
CHAT_AHEAD_S = float(J.get('chat.clock_offset_s', J.get('align.chat_clock_offset_s', 0.0)) or 0.0)
t0_wall = J.get('align.t0_wall') or J.source(J.ref_id()).get('t0_wall')  # recorder device start (ISO, local wall)
REF_T0 = 0.0
if t0_wall:
    d = datetime.fromisoformat(t0_wall)
    REF_T0 = d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6
PARTS = []
for p in J.parts():
    if (LAB.get('part_t0_msk') or {}).get(p):
        t0 = sec(LAB['part_t0_msk'][p])
    else:
        t0 = REF_T0 + TL['offsets'][p]['start_in_plaud']
    PARTS.append((p, t0, TL['files'][p]['duration']))


def video_pos(ts):
    p = ts - CHAT_AHEAD_S
    if p < PARTS[0][1]:
        return f'before_{PARTS[0][0]}', None
    for i, (part, t0, dur) in enumerate(PARTS):
        if t0 <= p <= t0 + dur:
            return part, round(p - t0, 1)
        nxt = PARTS[i + 1][1] if i + 1 < len(PARTS) else None
        if nxt is not None and t0 + dur < p < nxt:
            return 'gap', None
    return f'after_{PARTS[-1][0]}', None


# ---------- messages ----------
saved = J.data('chat/raw_parsed.json', [])
SAVED_NAME = os.path.basename(J.get('chat.saved_chat') or 'saved_chat')
CLIENT_NAME = os.path.basename(J.get('chat.client_log') or 'client_log')
msgs = [dict(src=SAVED_NAME, src_idx=i, time_msk=m['time_msk'], frm=m['frm'], text=m['text']) for i, m in enumerate(saved)]
extra = J.data('chat/extra_messages.json', []) if os.path.exists(OUT + 'extra_messages.json') else []
EXTRA = [dict(src=CLIENT_NAME if x.get('src', 'client_log') == 'client_log' else x['src'], src_idx=x['src_idx'], time_msk=x['time_msk'], frm=x['frm'], text=x['text']) for x in extra]
allm = msgs + EXTRA
if LAB.get('order', 'time') == 'time':
    allm.sort(key=lambda m: (sec(m['time_msk']), 0 if isinstance(m['src_idx'], int) else 1,
                             m['src_idx'] if isinstance(m['src_idx'], int) else 0))

TEAM = {k: v['display'] for k, v in (LAB.get('team') or {}).items()}
TEAM_ID = {k: v['id'] for k, v in (LAB.get('team') or {}).items()}
NAME = LAB.get('names') or {}
ANON = LAB.get('anonymous_name', 'Участник')
DEVICE = re.compile(r'^(iphone|ipad|android|galaxy|samsung|xiaomi|redmi|huawei|macbook|pc|desktop|host|user|guest)\b', re.I)


def display_name(frm):
    """first name only; e-mail / nickname / device / company / unknown accounts -> «Участник» (G-C4)"""
    if frm in NAME:
        return NAME[frm]
    s = frm.strip()
    if '@' in s or DEVICE.match(s) or not re.match(r'^[A-ZА-ЯЁ][a-zа-яё\-]+$', s.split()[0] if s.split() else ''):
        return ANON
    return s.split()[0]


POLL_IDX = {}
for pid, ids in (LAB.get('polls') or {}).items():
    for i in ids:
        POLL_IDX[ikey(i)] = pid
KIND = {}
for k, ids in (LAB.get('kinds') or {}).items():
    for i in ids:
        KIND[ikey(i)] = k
POLL_KIND_FORCE = {ikey(i) for i in LAB.get('poll_kind_force', [])}
HIDE = {}
for h in LAB.get('hide', []):
    for i in h['ids']:
        HIDE[ikey(i)] = h['reason']
HIGHLIGHT = idmap(LAB.get('highlight'))
OVERRIDE = idmap(LAB.get('override'))
EDIT_NOTE = idmap(LAB.get('edit_note'))
MANUAL_REPLY = {k: tuple(v) for k, v in idmap(LAB.get('manual_reply')).items()}
MENTION_FIX = [tuple(x) for x in LAB.get('mention_fix', [])]
MAXC = int(LAB.get('max_chars', 180))
RMAXC = int(LAB.get('reply_max_chars', 70))

URL_RE = re.compile(r'(https?://\S+|t\.me/\S+|www\.\S+)')
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
PHONE_RE = re.compile(r'(?<!\d)(\+?\d[\d\s\-()]{9,}\d)')


def clean(s):
    had_mention = s.lstrip().startswith('@')
    s = URL_RE.sub('', s)
    s = EMAIL_RE.sub('', s)
    s = PHONE_RE.sub('', s)
    for p, r in MENTION_FIX:
        s = re.sub(p, r, s)
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\s*-\s*$', '', s.strip())
    s = re.sub(r'^\s*-\s*', '', s)
    s = re.sub(r'\n{3,}', '\n\n', s).strip()
    if had_mention and s:
        s = s[0].upper() + s[1:]
    return s


def shorten(s, n=180):
    if len(s) <= n:
        return s, False
    cut = s[:n - 1]
    sp = cut.rfind(' ')
    if sp > n * 0.6:
        cut = cut[:sp]
    return cut.rstrip(' ,.;:—-') + '…', True


def norm(s):
    return re.sub(r'\s+', ' ', s).strip().rstrip('.').strip()


REPLY_RE = re.compile(r'^(?:Ответ на|Reply to|Replying to) «(.*?)»:\n(.*)$', re.S)


def body_of(m):
    b = m['text']
    mm = REPLY_RE.match(b)
    if mm:
        return mm.group(2)
    if m['src_idx'] in MANUAL_REPLY:
        return MANUAL_REPLY[m['src_idx']][1]
    return b


# ---------- reactions -> target message ----------
react_events = J.data('chat/reactions_parsed.json', []) if os.path.exists(OUT + 'reactions_parsed.json') else []
meta = J.data('chat/parse_meta.json', {}) if os.path.exists(OUT + 'parse_meta.json') else {}
CLIENT_START = meta.get('client_log_start')
REACT = {}
unmatched_reacts = []
for ev in react_events:
    evs = sec(ev['t'])
    cand = None
    trunc = ev.get('trunc', False)
    for m in allm:
        if sec(m['time_msk']) > evs + 5:
            break
        b = norm(body_of(m))
        full = norm(m['text'])
        ok = (b.startswith(ev['target']) or full.startswith(ev['target'])) if trunc else (b == ev['target'] or full == ev['target'])
        if ok:
            cand = m
    if cand is None:
        unmatched_reacts.append(ev)
        continue
    r = REACT.setdefault(cand['src_idx'], Counter())
    r[ev['emoji']] += ev.get('sign', 1)

# ---------- display list ----------
author_ids = {}
display = []
for seq, m in enumerate(allm):
    i = m['src_idx']
    frm = m['frm']
    is_team = frm in TEAM
    if is_team:
        dn, aid = TEAM[frm], TEAM_ID[frm]
    else:
        dn = display_name(frm)
        if frm not in author_ids:
            author_ids[frm] = 'p%02d' % (len(author_ids) + 1)
        aid = author_ids[frm]
    reply_to = None
    txt = m['text']
    mm = REPLY_RE.match(txt)
    if mm:
        reply_to, txt = mm.group(1), mm.group(2)
    elif i in MANUAL_REPLY:
        reply_to, txt = MANUAL_REPLY[i]
    orig_body = txt
    txt = OVERRIDE.get(i, clean(txt))
    if reply_to:
        reply_to = clean(reply_to).replace('...', '…')
        reply_to, _ = shorten(reply_to, RMAXC)
    txt, was_short = shorten(txt, MAXC)
    pid = POLL_IDX.get(i)
    if is_team:
        k = 'team_reply'
    elif pid and (i not in KIND or i in POLL_KIND_FORCE):
        k = 'answer_to_poll'
    elif i in KIND:
        k = KIND[i]
    else:
        k = 'question' if '?' in txt else 'other'
    show = i not in HIDE
    ts = sec(m['time_msk'])
    part, vt = video_pos(ts)
    rx = {e: c for e, c in REACT.get(i, Counter()).items() if c > 0}
    known = CLIENT_START is not None and ts >= sec(CLIENT_START)
    rec = OrderedDict(
        id=seq + 1, time_msk=m['time_msk'], display_name=dn, text=txt, kind=k, show=show,
        highlight=bool(show and i in HIGHLIGHT),
        author_id=aid, is_team=is_team, reply_to=reply_to, poll_id=pid,
        reactions=rx if rx else ({} if known else None),
        est_part=part, est_video_t=vt,
        hide_reason=HIDE.get(i), highlight_note=HIGHLIGHT.get(i) if (show and i in HIGHLIGHT) else None,
        edited=(txt != orig_body.strip()),
        src=m['src'], src_idx=i,
    )
    if i in EDIT_NOTE:
        rec['edit_note'] = EDIT_NOTE[i]
    display.append(rec)

# ---------- privacy self-check on shown texts (external oracle for this stage) ----------
surnames = set(LAB.get('privacy_surnames', []))
for frm in set(m['frm'] for m in allm):  # every word of every Zoom name except the shown first name
    parts_ = re.split(r'[\s()]+', frm)
    for w in parts_[1:]:
        if len(w) >= 3:
            surnames.add(w)
    if '@' in frm or not re.match(r'^[A-ZА-ЯЁ]', frm):
        surnames.add(frm.split('@')[0])
surnames -= set(LAB.get('privacy_allow', []))  # e.g. a city in a Zoom name that people also write in texts
shown_names = {d['display_name'] for d in display}
viol = []
for d in display:
    blob = (d['text'] or '') + ' ' + (d['reply_to'] or '') + ' ' + d['display_name']
    if URL_RE.search(blob) or EMAIL_RE.search(blob) or PHONE_RE.search(blob) or '@' in blob:
        viol.append((d['id'], 'link/email/phone/@', blob[:80]))
    for s in surnames:
        if s and s not in shown_names and re.search(r'(?<!\w)' + re.escape(s) + r'(?!\w)', blob):
            viol.append((d['id'], s, blob[:80]))
viol_shown = [v for v in viol if next(x for x in display if x['id'] == v[0])['show']]

with open(OUT + 'chat_display.json', 'w', encoding='utf-8', newline='\n') as f:
    json.dump(display, f, ensure_ascii=False, indent=1)
with open(OUT + '_build_diag.json', 'w', encoding='utf-8', newline='\n') as f:
    json.dump(dict(unmatched_reactions=unmatched_reacts, privacy_hits_all=viol, privacy_hits_shown=viol_shown), f, ensure_ascii=False, indent=1)

print('messages', len(display), 'shown', sum(d['show'] for d in display), 'highlight', sum(d['highlight'] for d in display))
print('kinds', Counter(d['kind'] for d in display))
print('kinds shown', Counter(d['kind'] for d in display if d['show']))
print('react events', len(react_events), 'unmatched', len(unmatched_reacts))
for u in unmatched_reacts:
    print('  UNMATCHED', u)
print('privacy hits (shown):', viol_shown)
print('privacy hits (all):', len(viol))
print('parts', Counter(d['est_part'] for d in display))
if viol_shown:
    sys.exit('privacy check FAILED on shown messages - hide/override them in chat_labels.json')
