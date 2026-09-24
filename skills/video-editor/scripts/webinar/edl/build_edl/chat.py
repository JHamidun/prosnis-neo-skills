"""Chat column, votes and reactions on the output clock (S10 step 9, gotchas G-C1..G-C5, G-S10).

Order = order of ARRIVAL (the saved-chat stamps are the SENDER's device clocks): median of 7 stamps, then a running
max; chat clock -> reference clock via chat_clock_offset_s (calibrated in S2 when the host reads messages aloud).
Bubble heights are measured with the real fonts (PIL) so the column reflows exactly like Remotion draws it.

edl_config.json:
  fonts                {"name": "fonts/Manrope-Bold.ttf", "text": "fonts/Manrope-Medium.ttf", "hl": "fonts/Manrope-SemiBold.ttf"}
  chat_col_w           368 (px of the chat column)
  chat_gap_to          ["part2", 0.0]   messages in the recording gap between parts land at the next part start
  reaction_lead_s      1.5
  polls[].keymap / key_rules          see polls.py (a vote is shown as a vote chip, not as a bubble)
  final_vote           {"poll_id": "...", "rules": [["contains", "СИН", "С"], ["regex", "\\s*[СC]\\b.*", "С"], ["else", "К"]]}
"""
from __future__ import annotations

import hashlib
import re

from PIL import ImageFont

from .ctx import hms, rule_key


def wrap_lines(text, font, width):
    words = text.split()
    lines, cur = [], ''
    for w in words:
        cand = (cur + ' ' + w).strip()
        if font.getlength(cand) <= width or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


class Fonts:
    def __init__(self, X):
        CH = X.CH
        self.name = ImageFont.truetype(X.font('name', 'fonts/Manrope-Bold.ttf'), CH['name_px'])
        self.text = ImageFont.truetype(X.font('text', 'fonts/Manrope-Medium.ttf'), CH['text_px'])
        self.hl = ImageFont.truetype(X.font('hl', 'fonts/Manrope-SemiBold.ttf'), CH['highlight']['text_px'])


def name_color(X, author):
    return X.PALETTE[int(hashlib.md5(author.encode()).hexdigest(), 16) % len(X.PALETTE)]


def poll_key(pspec, opt):
    """vote key of one chat answer: keymap by first character, or ordered key_rules on the option text."""
    if pspec.get('keymap'):
        return pspec['keymap'].get(opt[:1]) if opt else None
    if pspec.get('key_rules'):
        return rule_key(opt or '', pspec['key_rules'])
    return None


def build_chat(X, S):
    FPS, F, CH = X.FPS, S.F, X.CH
    FT = Fonts(X)
    S.fonts = FT
    items, votes_by_poll = [], {}
    final_votes = []
    msgs = sorted([m for m in X.CHAT if m.get('show')], key=lambda m: m['id'])
    raw = [hms(m['time_msk']) for m in msgs]
    sm = []
    for i in range(len(raw)):
        win = raw[max(0, i - 3):i + 4]
        sm.append(sorted(win)[len(win) // 2])
    run = -1e9
    for i in range(len(sm)):
        run = max(run, sm[i])
        sm[i] = run
    S.msgs, S.msg_t = msgs, sm
    inner = X.cfg.get('chat_col_w', 368) - 2 * CH['bubble_pad'][1]
    S.inner = inner
    pspecs = {p['id']: p for p in X.cfg.get('polls', [])}
    poll_votes_src = {}
    for p in X.STATS['polls']:
        for v in p.get('votes', []) or []:
            if 'id' in v and 'option' in v:
                poll_votes_src[v['id']] = (p['poll_id'], v['option'])
    fv_cfg = X.cfg.get('final_vote') or {}
    fpid = fv_cfg.get('poll_id')
    if fpid:  # final pill: voters listed by time/name/raw text -> match the chat message, key from the text
        fpv = next((p for p in X.STATS['polls'] if p['poll_id'] == fpid), {})
        for v in fpv.get('pill_voters', []):
            m = next((x for x in msgs if x['time_msk'] == v['time_msk'] and x['text'].strip() == v['raw'].strip()), None)
            if m is None:
                m = next((x for x in msgs if x['time_msk'] == v['time_msk'] and x['display_name'].startswith(v['display_name'])), None)
            if m is not None:
                final_votes.append((m['id'], rule_key(v['raw'].upper(), fv_cfg['rules'])))
    pre_intro = []
    first_extra = next(iter(X.extra), None)
    gap_to = X.cfg.get('chat_gap_to', [X.parts[-1], 0.0])
    for m, t_chat in zip(msgs, sm):
        src, st = X.plaud_to_src(t_chat - X.CHAT_MINUS_DEV - X.DEV0)
        if src == 'gap':
            src, st = gap_to[0], gap_to[1]
        if first_extra and src == first_extra and st < X.range_start.get(first_extra, 0.0):
            pre_intro.append(m)
            continue
        fr_ = F(src, st) if src in X.W else None
        if fr_ is None:
            continue
        team = bool(m['is_team'])
        name = m['display_name'].replace(' · команда', '')
        color = name_color(X, m['author_id'] or name)
        fv = next((k for i_, k in final_votes if i_ == m['id']), None)
        if fv:
            votes_by_poll.setdefault(fpid, []).append({'frame': fr_, 'key': fv})
        pv = poll_votes_src.get(m['id'])
        if pv and pv[0] in pspecs and pv[0] != fpid:
            pid, opt = pv
            key = poll_key(pspecs[pid], opt)
            if key:
                votes_by_poll.setdefault(pid, []).append({'frame': fr_, 'key': key})
                items.append({'id': m['id'], 'frame': fr_, 'name': name, 'text': m['text'], 'team': team, 'h': 46, 'hl': False, 'color': color, 'vote': key})
                continue
        hl = bool(m['highlight'])
        font = FT.hl if hl else FT.text
        lines = wrap_lines(m['text'].replace('\n', ' '), font, inner)
        if len(lines) > CH['text_max_lines']:
            lines = lines[:CH['text_max_lines']]
            lines[-1] = lines[-1][: max(0, len(lines[-1]) - 2)] + '…'
        text = ' '.join(lines)
        tpx = CH['highlight']['text_px'] if hl else CH['text_px']
        h = CH['bubble_pad'][0] * 2 + round(CH['name_px'] * 1.3) + 4 + round(len(lines) * tpx * CH['text_line_height'])
        if hl and '?' in text:
            h += 26
        items.append({'id': m['id'], 'frame': fr_, 'name': name, 'text': text, 'team': team, 'h': h, 'hl': hl, 'color': color, 'reply': None})
    # waiting-room greetings already in the column when the broadcast starts: they land while the first chapter
    # card hides the column, so it comes back already filled (9 >= tail max_visible + 3: teaser bubbles leave)
    c1 = S.card_frames[0][0]
    pre_items = []
    for k, m in enumerate(pre_intro[-9:]):
        name = m['display_name'].replace(' · команда', '')
        lines = wrap_lines(m['text'].replace('\n', ' '), FT.text, inner)[:CH['text_max_lines']]
        h = CH['bubble_pad'][0] * 2 + round(CH['name_px'] * 1.3) + 4 + round(len(lines) * CH['text_px'] * CH['text_line_height'])
        pre_items.append({'id': m['id'], 'frame': c1 + 20 + k * 6, 'name': name, 'text': ' '.join(lines), 'team': bool(m['is_team']),
                          'h': h, 'hl': False, 'color': name_color(X, m['author_id'] or name), 'reply': None})
    # reactions -> badge on the target bubble + floating icons (Zoom does not record them in the video, G-C5)
    reactions = []
    lead = X.cfg.get('reaction_lead_s', 1.5)
    for r in X.REACT:
        src, st = X.plaud_to_src(hms(r['t']) - lead - X.CHAT_MINUS_DEV - X.DEV0)
        if src not in X.W:
            continue
        fr_ = F(src, st)
        if fr_ is None:
            continue
        target = next((it for it in items if not it.get('vote') and it['text'].startswith(r['target'][:18])), None)
        if target is not None:
            target.setdefault('reacts', []).append({'frame': max(fr_, target['frame'] + 6), 'emoji': r['emoji']})
            fr_ = max(fr_, target['frame'] + 6)
        reactions.append({'frame': fr_, 'kind': r['emoji'], **({'msgId': target['id']} if target else {})})
    items.sort(key=lambda it: it['frame'])
    last = -10**9
    for it in items:
        if it['frame'] < last + CH['min_interval_frames'] and it['frame'] > 0:
            it['frame'] = last + CH['min_interval_frames']
        last = it['frame']
    for it in items:  # bubbles must not pop under a chapter card: push to the card end (G-S10)
        for a, b in S.card_ranges:
            if a <= it['frame'] < b:
                it['frame'] = b + 4
    items = sorted(pre_items + items, key=lambda it: it['frame'])
    reactions.sort(key=lambda r: r['frame'])
    for r in reactions:
        for a, b in S.card_ranges:
            if a <= r['frame'] < b:
                r['frame'] = b + 6
    S.chat_items, S.votes_by_poll, S.reactions = items, votes_by_poll, reactions


def teaser_chat(X, S):
    """the teaser shows the REAL chat of those minutes, re-timed into the teaser windows (never invented)."""
    CH = X.CH
    tchat = []
    for (src, a, b), f0 in zip(S.teaser, S.teaser_from):
        for m, t_chat in zip(S.msgs, S.msg_t):
            s2, st = X.plaud_to_src(t_chat - X.CHAT_MINUS_DEV - X.DEV0)
            if s2 == src and a - 40 <= st <= b and not m['is_team']:
                name = m['display_name']
                lines = wrap_lines(m['text'].replace('\n', ' '), S.fonts.text, S.inner)[:CH['text_max_lines']]
                h = CH['bubble_pad'][0] * 2 + round(CH['name_px'] * 1.3) + 4 + round(len(lines) * CH['text_px'] * CH['text_line_height'])
                tchat.append({'id': 100000 + m['id'], 'frame': f0 + max(-60, min(X.fr(b - a) - 10, X.fr(st - a))), 'name': name,
                              'text': ' '.join(lines), 'team': False, 'h': h, 'hl': False, 'color': name_color(X, m['author_id'] or name), 'reply': None})
    tchat.sort(key=lambda x: x['frame'])
    S.chat_items = tchat[-8:] + S.chat_items
