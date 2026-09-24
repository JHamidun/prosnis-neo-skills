"""Poll cards from chat votes, the per-clip quiz counter and the final rating (S10 step 10).

A poll card opens at the host's prompt (or 2 s before the first vote), never more than 20 s before the first vote,
holds 4 s after the last vote (>= 10 s), polls never overlap (the earlier one is trimmed, >= 5 s).

edl_config.json:
  polls [{"id": "<chat_stats poll_id>", "keymap": {"К": "К", "K": "К"} | null, "key_rules": [...] | null,
          "title": "…" (no title = votes become vote chips but no card), "options": [["К", "красная — хочу знать"], ...],
          "prompt": [src, a, b, "regex of the prompt word"], "reveal": "1" | null}]
  quiz  {"stats_poll_id": "…", "id": "truth_or_ai", "src": "part1", "start_t": 276.0, "letters": "ABCDEF",
         "tokens": {"ИИ": ["ИИ", "Л", "B"], "П": ["ПРАВДА", "ПРВДА", "П", "A"]}, "vote_for": "ИИ",
         "kicker": "…", "title": "…", "option_labels": ["ролик A", ...]}
  rating_stat {"poll_id": "…", "value": 10, "prefix": "оценка эфира: ", "suffix": " из 10", "at": [262, 790], "size": 44}
"""
from __future__ import annotations

import re


def build_polls(X, S):
    FPS, F, ck = X.FPS, S.F, S.ck
    kicker = X.cfg.get('poll_kicker', 'ОПРОС В ЧАТЕ')

    def prompt_frame(src, a, b, rx):
        w = X.find_word(src, a, b, rx)
        return F(src, w['start']) if w and ck.inside(src, w['start']) else None

    polls = []
    for ps in X.cfg.get('polls', []):
        if not ps.get('title'):
            continue
        pid = ps['id']
        vs = sorted(S.votes_by_poll.get(pid, []), key=lambda v: v['frame'])
        if not vs:
            S.report['warnings'].append(f'poll {pid}: no votes mapped')
            continue
        src, a, b, rx = ps['prompt']
        pf = prompt_frame(src, a, b, rx)
        f0 = min(vs[0]['frame'] - 25, pf if pf is not None else vs[0]['frame'] - 50)
        f0 = max(f0, vs[0]['frame'] - 20 * FPS)
        f1 = max(vs[-1]['frame'] + 4 * FPS, f0 + 10 * FPS)
        p = {'id': pid, 'from': int(f0), 'to': int(f1), 'kicker': kicker, 'title': ps['title'],
             'options': [{'key': k, 'label': l} for k, l in ps['options']], 'votes': vs}
        if ps.get('reveal'):
            p['reveal'] = {'frame': int(f1 - 30), 'key': ps['reveal']}
        polls.append(p)

    def no_overlap():
        polls.sort(key=lambda p: p['from'])
        for a, b in zip(polls, polls[1:]):
            if a['to'] > b['from'] - 14:
                a['to'] = max(a['from'] + 5 * FPS, b['from'] - 14)

    no_overlap()
    qz = X.cfg.get('quiz')
    q = next((p for p in X.STATS['polls'] if qz and p['poll_id'] == qz['stats_poll_id']), None)
    if q:  # quiz: votes are free text per person -> per-clip counter of one answer
        tokmap = {t: k for k, lst in qz['tokens'].items() for t in lst}
        rx = re.compile('|'.join(sorted(map(re.escape, tokmap), key=lambda s: (-len(s), s))))
        rx = re.compile(qz.get('token_regex')) if qz.get('token_regex') else rx
        letters = qz.get('letters', 'ABCDEF')
        pvotes = []
        for person in q.get('people', []):
            src, st = X.chat_src_time(person['time_msk'])
            if src != qz['src']:
                continue
            fr_ = F(src, st)
            raw_t = person.get('raw', '')
            m = re.search(r'«([^»]+)»', raw_t)
            s = (m.group(1) if m else raw_t).upper().replace('Ё', 'Е')
            seq = [tokmap[tk] for tk in rx.findall(s) if tk in tokmap]
            for i, v in enumerate(seq[:len(letters)]):
                if v == qz.get('vote_for', 'ИИ'):
                    pvotes.append({'frame': fr_ + i * 3, 'key': letters[i]})
        if pvotes:
            pvotes.sort(key=lambda v: v['frame'])
            f0 = F(qz['src'], qz['start_t'])
            polls.append({'id': qz['id'], 'from': f0, 'to': max(pvotes[-1]['frame'] + 5 * FPS, f0 + 30 * FPS), 'kicker': qz['kicker'],
                          'title': qz['title'], 'options': [{'key': k, 'label': l} for k, l in zip(letters, qz['option_labels'])],
                          'votes': pvotes})
    no_overlap()
    rs = X.cfg.get('rating_stat')
    fp = next((p for p in polls if rs and p['id'] == rs['poll_id']), None)
    if fp:  # final rating as a count-up stat doodle when the votes are in
        S.doodles.append({'type': 'stat', 'from': fp['to'] - 6 * FPS, 'to': fp['to'] + 4 * FPS, 'at': rs.get('at', [262, 790]),
                          'value': rs['value'], 'prefix': rs.get('prefix', ''), 'suffix': rs.get('suffix', ''), 'size': rs.get('size', 44)})
    S.polls = polls
