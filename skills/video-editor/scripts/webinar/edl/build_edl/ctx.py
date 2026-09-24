"""Inputs, config and helpers shared by every module of the EDL builder (S10).

Everything the reference run had as constants in build_full_edl.py lives in edl/edl_config.json of the job
(schema: templates/edl_config.example.json, reference: references/webinar-montage.md S10). The builder itself holds
only the rules (style.md) - no names, no times, no paths of a particular webinar.
"""
from __future__ import annotations

import bisect
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from job import load  # noqa: E402

FILLER = re.compile(r'^(э+|ээ+|мм+|м-м|эм+)[.,!?…]*$', re.I)
# Russian stop words for the key-word pill of the captions (never pill a function word)
STOP_RU = set('это этот эта эти что как так вот там тут уже еще ещё если чтобы потому который которые которых очень '
              'просто может можно нужно было были будет будут даже тоже когда тогда вообще наверное сегодня такой '
              'такие такого такая где-то кстати значит вдруг потом буквально пожалуйста интересно конечно '
              'действительно разобраться сразу немножко примерно соответственно получается собственно'.split())


def hms(s):
    h, m, x = s.split(':')
    return int(h) * 3600 + int(m) * 60 + float(x)


def tc(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


_TOK = re.compile(r'\s*([+-]?)\s*([A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?)')


def ev(x, names: dict):
    """Frame expression of the config: a number, or 'name', 'name+24', 'fc+16', 't_end-6', 'b0+10+225'.
    Only sums of known names and numbers - no eval()."""
    if isinstance(x, (int, float)):
        return x
    s = str(x).strip()
    pos, total, seen = 0, 0, False
    while pos < len(s):
        m = _TOK.match(s, pos)
        if not m or m.end() == pos:
            raise ValueError(f'bad frame expression {x!r}')
        sign, tok = m.group(1), m.group(2)
        if tok[0].isdigit():
            v = float(tok) if '.' in tok else int(tok)
        else:
            if tok not in names:
                raise KeyError(f'unknown name {tok!r} in frame expression {x!r} (known: {sorted(names)})')
            v = names[tok]
        total = total - v if sign == '-' else total + v
        pos = m.end()
        seen = True
    if not seen:
        raise ValueError(f'empty frame expression {x!r}')
    return total


def rule_key(text: str, rules) -> str | None:
    """Key of a free-text answer by ordered rules: [["startswith", "1", "1"], ["contains", "1956", "56"],
    ["equals", "56", "56"], ["regex", "\\s*[СC]\\b.*", "С"], ["else", "ИИ"]]."""
    for r in rules:
        op = r[0]
        if op == 'else':
            return r[1]
        arg, key = r[1], r[2]
        if (op == 'startswith' and text.startswith(arg)) or (op == 'contains' and arg in text) or \
                (op == 'equals' and text.strip() == arg) or (op == 'regex' and re.fullmatch(arg, text)):
            return key
    return None


def check_font(path: str) -> str:
    """G-F1: files named *.ttf in a user font folder can be saved HTML pages - check the signature."""
    head = open(path, 'rb').read(4)
    if head not in (b'\x00\x01\x00\x00', b'OTTO', b'true', b'ttcf'):
        raise SystemExit(f'{path}: not a TrueType/OpenType font (first bytes {head!r}) - see webinar-gotchas G-F1')
    return path


class Ctx:
    """Read-only inputs of one build."""

    def __init__(self):
        self.J = J = load()
        self.cfg: dict = J.data('edl/edl_config.json')
        C = self.cfg
        self.FPS = J.fps
        self.OUT = Path(J.p('edl'))
        self.PUB = Path(J.p('remotion/public'))
        self.TOK = json.load(open(J.p('style/tokens.json'), encoding='utf-8'))
        self.LAY = self.TOK['layout']
        self.CH = self.TOK['chat']
        self.PALETTE = self.TOK['color']['name_palette']
        self.CARD = self.TOK['chapter_card']['duration_frames']
        self.TL = json.load(open(J.p('timeline.json'), encoding='utf-8'))
        self.SC = json.load(open(J.p('vision/scenes.json'), encoding='utf-8'))
        self.CHAT = json.load(open(J.p('chat/chat_display.json'), encoding='utf-8'))
        self.STATS = json.load(open(J.p('chat/chat_stats.json'), encoding='utf-8'))
        self.REACT = json.load(open(J.p('chat/reactions_parsed.json'), encoding='utf-8'))
        self.VSYNC = self._opt_json(self.OUT / 'vsync.json')
        self.VSYNCV = self._opt_json(self.OUT / 'vsync_vis.json')
        self.parts = J.parts()                         # aligned parts (part1, part2 ...)
        self.extra = C.get('extra_sources', {})        # recorder-only pieces (e.g. "intro": {"timeline_key": "intro_plaud"})
        self.audio_only = set(C.get('audio_only_sources', list(self.extra)))
        self.tags = {tag: sid for tag, sid in J.vision_tags().items()}
        self.W = self._load_words()
        self.WSTART = {p: [w['start'] for w in ws] for p, ws in self.W.items()}
        self.range_start = {r[0]: float(r[1]) for r in C['ranges']}
        self.stop = set(C.get('stop_words', [])) or STOP_RU
        self.drop_words = set(w.lower() for w in (C.get('drop_words') or J.get('transcript.drop_words', []) or []))
        self.drop_words |= {w + ',' for w in self.drop_words}
        t0_wall = C.get('reference_t0_wall_msk') or (J.get('align.t0_wall') or J.source(J.ref_id()).get('t0_wall'))
        self.DEV0 = hms(t0_wall.split('T')[-1][:12]) if 'T' in t0_wall else hms(t0_wall)
        off = C.get('chat_clock_offset_s', J.get('chat.clock_offset_s', J.get('align.chat_clock_offset_s')))
        self.CHAT_MINUS_DEV = float(off)

    @staticmethod
    def _opt_json(p):
        return json.load(open(p, encoding='utf-8')) if Path(p).exists() else {}

    def _words_file(self, src):
        files = self.J.get('transcript.words_files', {}) or {}
        if src in files:
            return self.J.rel(files[src])
        key = (self.extra.get(src) or {}).get('timeline_key')
        if key and self.TL['files'].get(key, {}).get('words'):
            return self.TL['files'][key]['words']
        return self.J.p(f'transcript/{src}.words.json')

    def _load_words(self):
        W = {}
        for p in list(self.parts) + list(self.extra):
            W[p] = json.load(open(self._words_file(p), encoding='utf-8'))['words']
        return W

    def words_json(self, src):
        return json.load(open(self._words_file(src), encoding='utf-8'))

    def src_audio(self, src):
        if src in self.extra:
            key = self.extra[src].get('timeline_key')
            return self.extra[src].get('audio') and self.J.rel(self.extra[src]['audio']) or self.TL['files'][key]['audio']
        return self.TL['files'][src]['original']

    # ---- time helpers
    def fr(self, t):
        return int(round(t * self.FPS))

    def snap(self, t):
        return round(t * self.FPS) / self.FPS

    def words_between(self, part, a, b):
        i = bisect.bisect_left(self.WSTART[part], a - 1e-6)
        j = bisect.bisect_right(self.WSTART[part], b)
        return self.W[part][i:j]

    def find_word(self, part, a, b, pattern):
        rx = re.compile(pattern, re.I)
        for w in self.words_between(part, a, b):
            if rx.search(w['punctuated_word']):
                return w
        return None

    def find_phrase(self, part, a, b, phrase):
        """first word of `phrase` (1-4 words, fuzzy by normalized tokens) in [a,b] -> word dict"""
        if not phrase:
            return None
        toks = [re.sub(r'[^\w]', '', t.lower()) for t in phrase.split()][:4]
        toks = [t for t in toks if t]
        if not toks:
            return None
        ws = self.words_between(part, a, b)
        norm = [re.sub(r'[^\w]', '', w['punctuated_word'].lower()) for w in ws]
        for i in range(len(ws)):
            ok = 0
            for k, t in enumerate(toks):
                if i + k < len(ws) and (norm[i + k] == t or (len(t) > 4 and norm[i + k][:5] == t[:5])):
                    ok += 1
            if ok >= max(1, len(toks) - (1 if len(toks) >= 3 else 0)):
                return ws[i]
        return None

    # ---- reference-recorder clock -> source time (timeline.json knots)
    def knots(self, part):
        k = self.TL['offsets'].get('part_to_plaud_knots') or {}
        dur = self.TL['files'][part]['duration']
        if part in k:
            arr = np.array(k[part], dtype=float)  # [t, offset], plaud = t + offset
            t = np.concatenate([[0.0], arr[:, 0], [dur]])
            off = np.concatenate([[arr[0, 1]], arr[:, 1], [arr[-1, 1]]])
            return t, t + off
        o = self.TL['offsets'][part]
        return np.array([0.0, dur]), np.array([o['start_in_plaud'], o['end_in_plaud']])

    def plaud_to_src(self, p):
        """reference time -> (src, t); before the first part -> the recorder-only extra source (if any)"""
        for part in self.parts:
            t, pl = self.knots(part)
            if pl[0] - 0.5 <= p <= pl[-1] + 0.5:
                return part, float(np.interp(p, pl, t))
        if p < self.TL['offsets'][self.parts[0]]['start_in_plaud']:
            for src, spec in self.extra.items():
                key = spec.get('timeline_key')
                if key:
                    return src, p - self.TL['files'][key]['plaud_in']
        return 'gap', p

    def chat_src_time(self, chat_hms):
        return self.plaud_to_src(hms(chat_hms) - self.CHAT_MINUS_DEV - self.DEV0)

    # ---- slide data
    def boxes(self, n):
        p = self.OUT / f'boxes/boxes_{n:03d}.json'
        return json.load(open(p, encoding='utf-8')) if p.exists() else None

    @staticmethod
    def rect_norm(b, W=1920, H=1080):
        y0, x0, y1, x1 = b
        return [round(x0 / 1000 * W), round(y0 / 1000 * H), round((x1 - x0) / 1000 * W), round((y1 - y0) / 1000 * H)]

    def sketch_meta(self, n):
        p = self.PUB / f'full/sketch/{n:03d}.json'
        if not p.exists():
            return None
        d = json.load(open(p, encoding='utf-8'))
        return {'theme': d.get('theme'), 'els': [{'id': e['id'], 'kind': e.get('kind'), 'crop': e['crop'],
                                                  'ink': e.get('ink_px', 0) + e.get('acc_px', 0), 'label': e.get('label')}
                                                 for e in d['elements']]}

    def art_set(self):
        return {int(p.stem) for p in (self.PUB / 'full/art').glob('*.png')}

    def vt(self, spec):
        """time of a deck video / event: a number, {"vsync": key} (audio xcorr), {"vsync_vis": key} (motion), + "plus"."""
        if isinstance(spec, (int, float)):
            return float(spec)
        if 'vsync' in spec:
            base = self.VSYNC[spec['vsync']]['rec_time_of_video_t0']
        elif 'vsync_vis' in spec:
            base = self.VSYNCV[spec['vsync_vis']]['rec_time_of_video_t0']
        else:
            base = spec['t']
        return base + spec.get('plus', 0.0)

    def font(self, key, default):
        return check_font(self.J.rel((self.cfg.get('fonts') or {}).get(key, default)))
