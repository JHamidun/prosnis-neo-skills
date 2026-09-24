"""S5: chat/chat_stats.json - polls, quiz, final rating, participants, questions, cases, sync notes.

The EDL builder reads from here: polls[].votes[{id, option}] (burst polls -> poll cards), the rating poll's
pill_voters (final vote card), the quiz poll's people[] (per-clip counter). Everything the model cannot know
(which option a free-text answer means, the right answer, what the host asked) lives in chat_labels.json
"poll_specs" and is checked by a human against the transcript (build_stats never guesses a vote).

poll_specs[] (in output order), one of the modes:
  {"poll_id", "mode": "burst", "label", "prompt", "options": {...}, "correct": "...", "notes": "...",
   "votes": {"<id>": "<option>"} | "auto",        auto = first character of every answer labelled with this poll
   "share_correct_option": "<option>", "keep_order": false}  -> share_correct = counts[option] / respondents;
                                                   votes are taken in arrival order unless keep_order
  {"poll_id", "mode": "answers", "label", "prompt", "ids": [ids]}                       free answers
  {"poll_id", "mode": "mentions", "label", "prompt", "mentions": {"<id>": ["Claude", ...]}, "family": "Claude"}
  {"poll_id", "mode": "quiz", "label", "prompt", "key": {"A": "ИИ", ...},
   "people": {"<id>": {"answers": {"A": "ИИ", ...}, "raw": "how it was decoded"}}, "undecodable": [ids],
   "most_common_answer": "...", "notes": "..."}
  {"poll_id", "mode": "rating", "label", "prompt", "window_chat_msk": [a, b], "pill": {"<id>": "К"},
   "pill_options": ["К", "С"], "scores": {"<id>": 10}, "cap": 10, "method": "...", "change_vs_start": "..."}
Other optional keys of chat_labels.json used here: "empty_prompts" [{prompt, result}], "questions" [{id, answered}],
"cases" [{"key", "ids", "window_chat_msk", "est_video", "paraphrase", "note"}], "participants" {joined_unique,
join_records, notes, unknown_accounts: [...]}, "sync" {...}, "sources_note" {...}, "flags_for_video" [...].
usage: python build_stats.py --job job.json
"""
import json
import os
import re
import statistics
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
OUT = J.p('chat') + '/'
D = J.data('chat/chat_display.json')
LAB = J.data('chat/chat_labels.json', {})
raw = J.data('chat/raw_parsed.json', [])


def ikey(k):
    return int(k) if isinstance(k, str) and k.isdigit() else k


BY = {d['src_idx']: d for d in D}
RAWTXT = {i: r['text'] for i, r in enumerate(raw)}
RAWTXT.update({d['src_idx']: d['text'] for d in D if not isinstance(d['src_idx'], int)})
TEAM = set((LAB.get('team') or {}).keys())


def who(i):
    return BY[i]['display_name']


def t(i):
    return BY[i]['time_msk']


def aid(i):
    return BY[i]['author_id']


def sec(x):
    h, m, s = x.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def burst(pid, votes, label, prompt, options_note=None, correct=None, notes=None, extra=None):
    """votes: list of (src_idx, option) - the LAST answer of each participant counts; team excluded upstream"""
    last = OrderedDict()
    allv = []
    for i, opt in votes:
        allv.append(dict(time_msk=t(i), author_id=aid(i), display_name=who(i), option=opt, id=BY[i]['id']))
        last[aid(i)] = opt
    cnt = Counter(last.values())
    per_min = Counter(v['time_msk'][:5] for v in allv)
    r = OrderedDict(poll_id=pid, label=label, prompt=prompt,
                    window_chat_msk=[allv[0]['time_msk'], allv[-1]['time_msk']] if allv else None,
                    peak_minute=per_min.most_common(1)[0] if allv else None,
                    n_messages=len(allv), n_respondents=len(last), counts=dict(cnt.most_common()),
                    counting_rule='last answer per participant; team excluded')
    if correct:
        r['correct'] = correct
    if options_note:
        r['options'] = options_note
    if notes:
        r['notes'] = notes
    if extra:
        r.update(extra)
    r['votes'] = allv
    return r


def poll_answers(pid):
    return [d['src_idx'] for d in D if d.get('poll_id') == pid and not d['is_team']]


P = []
fin = None
for sp in LAB.get('poll_specs', []):
    pid, mode = sp['poll_id'], sp.get('mode', 'burst')
    if mode == 'burst':
        v = sp.get('votes', 'auto')
        if v == 'auto':
            pairs = [(i, (BY[i]['text'].strip()[:1] or '?').upper()) for i in poll_answers(pid)]
        else:
            pairs = [(ikey(k), o) for k, o in v.items()]
        if not sp.get('keep_order'):  # arrival order (= display id); keep_order: the order given in the spec
            pairs.sort(key=lambda kv: BY[kv[0]]['id'])
        b = burst(pid, pairs, sp.get('label'), sp.get('prompt'), sp.get('options'), sp.get('correct'), sp.get('notes'), sp.get('extra'))
        if sp.get('share_correct_option'):
            b['share_correct'] = round(b['counts'].get(sp['share_correct_option'], 0) / max(1, b['n_respondents']), 2)
        P.append(b)
    elif mode == 'answers':
        ids = [ikey(i) for i in sp.get('ids') or poll_answers(pid)]
        P.append(OrderedDict(poll_id=pid, label=sp.get('label'), prompt=sp.get('prompt'), n_respondents=len({aid(i) for i in ids}),
                             answers=[dict(time_msk=t(i), display_name=who(i), text=BY[i]['text']) for i in ids]))
    elif mode == 'mentions':
        tools = {ikey(k): v for k, v in sp['mentions'].items()}
        mentions = Counter(x for v in tools.values() for x in v)
        fam = sp.get('family')
        r = OrderedDict(poll_id=pid, label=sp.get('label'), prompt=sp.get('prompt'),
                        n_respondents=len({aid(i) for i in tools}), mentions=dict(mentions.most_common()))
        if fam:
            r[f'{fam.lower()}_family_people'] = len({aid(i) for i, v in tools.items() if any(fam in x for x in v)})
        r['votes'] = [dict(time_msk=t(i), display_name=who(i), tools=v) for i, v in tools.items()]
        if sp.get('notes'):
            r['notes'] = sp['notes']
        P.append(r)
    elif mode == 'quiz':
        KEY = sp['key']
        clips = list(KEY.keys())
        per_clip = {c: Counter() for c in clips}
        people = []
        for k, pr in sp['people'].items():
            i = ikey(k)
            ans = pr['answers']
            sc = sum(1 for c, v in ans.items() if KEY[c] == v)
            for c, v in ans.items():
                per_clip[c][v] += 1
            people.append(dict(time_msk=t(i), display_name=who(i), author_id=aid(i), raw=pr.get('raw', BY[i]['text']),
                               answered=len(ans), correct=sc))
        people.sort(key=lambda x: x['time_msk'])
        full = [p for p in people if p['answered'] == len(clips)]
        P.append(OrderedDict(
            poll_id=pid, label=sp.get('label'), prompt=sp.get('prompt'), correct=KEY,
            per_clip_votes={c: dict(per_clip[c]) for c in clips},
            per_clip_share_correct={c: round(per_clip[c][KEY[c]] / max(1, sum(per_clip[c].values())), 2) for c in clips},
            n_decodable_respondents=len(people), n_full_six=len(full),
            full_six_score_distribution=dict(Counter(p['correct'] for p in full)),
            best=max(full, key=lambda p: p['correct']) if full else None,
            mean_score_full_six=round(statistics.mean(p['correct'] for p in full), 2) if full else None,
            most_common_answer=sp.get('most_common_answer'),
            people=people,
            undecodable=[dict(time_msk=t(ikey(i)), display_name=who(ikey(i)), raw=RAWTXT.get(ikey(i), BY[ikey(i)]['text']))
                         for i in sp.get('undecodable', [])],
            notes=sp.get('notes')))
    elif mode == 'rating':
        pill = {ikey(k): v for k, v in (sp.get('pill') or {}).items()}
        score = {ikey(k): v for k, v in (sp.get('scores') or {}).items()}
        cap = sp.get('cap', 10)
        capped = [min(v, cap) for v in score.values()]
        strict = [v for v in score.values() if 1 <= v <= cap]
        opts = sp.get('pill_options') or sorted(set(v[:1] for v in pill.values()))
        fin = OrderedDict(
            poll_id=pid, label=sp.get('label'), prompt=sp.get('prompt'), window_chat_msk=sp.get('window_chat_msk'),
            pill_counts={o: sum(1 for v in pill.values() if v.startswith(o)) for o in opts},
            pill_voters=[dict(time_msk=t(i), display_name=who(i), raw=RAWTXT.get(i, BY[i]['text'])) for i in pill],
            rating=OrderedDict(
                n_raters=len(score), average_capped_1_10=round(statistics.mean(capped), 2) if capped else None,
                median=statistics.median(capped) if capped else None,
                average_strict_valid_only=round(statistics.mean(strict), 2) if strict else None, n_strict_valid=len(strict),
                share_10=round(sum(1 for v in capped if v == cap) / len(capped), 2) if capped else None,
                raw=[dict(time_msk=t(i), display_name=who(i), raw=RAWTXT.get(i, BY[i]['text']), score=v, capped=min(v, cap)) for i, v in score.items()],
                method=sp.get('method')),
        )
        if sp.get('change_vs_start'):
            fin['change_vs_start'] = sp['change_vs_start']
        P.append(fin)
    else:
        raise SystemExit(f'unknown poll mode {mode} ({pid})')

# ---------- participants ----------
names_all = Counter(r['frm'] for r in raw) + Counter(x['frm'] for x in (J.data('chat/extra_messages.json', []) if os.path.exists(OUT + 'extra_messages.json') else []))
nonteam = {n: c for n, c in names_all.items() if n not in TEAM}
PART = LAB.get('participants') or {}
unknown = set(PART.get('unknown_accounts', []))
first_pl = [d for d in D if not d['is_team']]
parts = OrderedDict(
    unique_nonteam_zoom_names_wrote=len(nonteam),
    unique_nonteam_excluding_unknown_accounts=len([n for n in nonteam if n not in unknown]),
    team_wrote=[v['display'] for k, v in (LAB.get('team') or {}).items() if any(d['is_team'] and d['display_name'] == v['display'] for d in D)],
    zoom_report_unique_names_joined=PART.get('joined_unique'), zoom_report_join_records=PART.get('join_records'),
    share_of_joined_who_wrote=(round(len(nonteam) / max(1, PART['joined_unique'] - len(TEAM)), 2) if PART.get('joined_unique') else None),
    messages_total=len(D), messages_nonteam=len(first_pl), messages_team=len(D) - len(first_pl),
    notes=PART.get('notes'),
)
top = Counter(r['frm'] for r in raw if r['frm'] not in TEAM).most_common(8)
first_idx = {}
for i, r in enumerate(raw):
    first_idx.setdefault(r['frm'], i)
parts['top_writers'] = [dict(display_name=BY[first_idx[n]]['display_name'], n=c) for n, c in top if first_idx.get(n) in BY]
pm = Counter(d['time_msk'][:5] for d in D if not d['is_team'])
parts['busiest_minutes'] = [dict(minute=m, n=c) for m, c in pm.most_common(8)]
parts['messages_by_kind_shown'] = dict(Counter(d['kind'] for d in D if d['show']))

# ---------- questions / cases ----------
top_q = []
for q in LAB.get('questions', []):
    i = ikey(q['id'])
    top_q.append(OrderedDict(time_msk=t(i), display_name=who(i), question=BY[i]['text'], answered=q.get('answered'),
                             shown_in_overlay=BY[i]['show']))
cases = OrderedDict()
for c in LAB.get('cases', []):
    ids = [ikey(i) for i in c['ids']]
    cases[c['key']] = OrderedDict(
        window_chat_msk=c.get('window_chat_msk'), est_video=c.get('est_video'), paraphrase=c.get('paraphrase'),
        reactions_total=sum(sum((BY[i]['reactions'] or {}).values()) for i in ids),
        messages=[dict(id=BY[i]['id'], time_msk=t(i), display_name=who(i), text=BY[i]['text'], highlight=BY[i]['highlight']) for i in ids],
        note=c.get('note'))

stats = OrderedDict(
    source=LAB.get('sources_note'),
    sync=LAB.get('sync') or OrderedDict(chat_clock_minus_reference_msk_s=J.get('chat.clock_offset_s')),
    participants=parts,
    polls=P,
    prompts_without_chat_answers=LAB.get('empty_prompts', []),
)
if fin:
    stats['final_rating_summary'] = OrderedDict(average=fin['rating']['average_capped_1_10'], n=fin['rating']['n_raters'],
                                                 all_ten=fin['rating']['share_10'] == 1.0, pill_final=fin['pill_counts'],
                                                 method=fin['rating']['method'])
stats['top_questions'] = top_q
stats.update(cases)
stats['display_summary'] = OrderedDict(total=len(D), shown=sum(d['show'] for d in D), hidden=sum(not d['show'] for d in D),
                                       highlights=sum(d['highlight'] for d in D),
                                       hidden_by_reason=dict(Counter(d['hide_reason'] for d in D if not d['show']).most_common()))
stats['flags_for_video'] = LAB.get('flags_for_video', [])
with open(OUT + 'chat_stats.json', 'w', encoding='utf-8', newline='\n') as f:
    json.dump(stats, f, ensure_ascii=False, indent=1)

for p in P:
    print(p['poll_id'], p.get('n_respondents', p.get('n_decodable_respondents')), p.get('counts', p.get('per_clip_votes', '')))
if fin:
    print('final', fin['pill_counts'], fin['rating']['average_capped_1_10'], fin['rating']['n_raters'])
print('participants', parts['unique_nonteam_zoom_names_wrote'], parts['unique_nonteam_excluding_unknown_accounts'], parts['share_of_joined_who_wrote'])
print('busiest', parts['busiest_minutes'][:5])
