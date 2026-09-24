"""Build transcript.data.json (the data contract of transcript.html) from the word-level ASR.

Sources: transcript/plaud_intro.words.json (intro piece, Plaud audio), transcript/part1.words.json,
transcript/part2.words.json. Timecodes = position in the edited video:

    edit_t = edit_in + (src_t - src_in)     for the timemap segment that contains src_t

Default timemap = timeline.json segments with recommended=true (PROVISIONAL: no intro sting, no
internal cuts). For the final PDF pass the montage EDL converted to the same shape:

    python build_transcript_data.py --timemap final_timemap.json --final
    final_timemap.json = {"segments": [{"source": "intro_plaud|part1|part2", "src_in": s, "src_out": s,
                                        "edit_in": s}, ...]}   # any number of pieces, cuts = gaps

Words whose source time falls outside every segment are dropped (cut from the video).
Chapters: data/transcript_chapters.json (phrase anchors -> resolved per run).
Redactions: data/transcript_redactions.json (fails if an expected hit is missing).
"""
import argparse, datetime, json, pathlib, re, sys

from _job import JOB, get

ROOT = pathlib.Path(__file__).resolve().parent


def _sources():
    """timemap source name -> words file: every timeline.json file entry with a 'words' path (recorder pieces, e.g.
    intro_plaud) + transcript/<part>.words.json of every aligned part"""
    out = {}
    tl = JOB / 'timeline.json'
    if tl.exists():
        for key, f in json.loads(tl.read_text(encoding='utf-8')).get('files', {}).items():
            if isinstance(f, dict) and f.get('words'):
                out[key] = pathlib.Path(f['words'])
    parts = get('align.parts') or [x['id'] for x in get('sources', []) if x.get('kind') != 'recorder']
    for sid in parts:
        out.setdefault(sid, JOB / f'transcript/{sid}.words.json')
    return out


SOURCES = _sources()
# ASR speaker name -> speaker id of data/transcript_doc.json "speakers" (filled in main() from the doc)
SPEAKERS = {}
FILLERS = {'ээ', 'эээ', 'эм', 'эмм', 'ммм', 'мм', 'э'}
TERMINAL = re.compile(r'[.?!…]["»)]*$')

# paragraph shaping (characters)
SOFT_MAX = 520     # break at the next sentence end after this length
HARD_MAX = 950     # break at the next comma after this length
GAP_BREAK = 2.2    # s of silence that allows a break at a sentence end once the paragraph has SOFT_MIN
SOFT_MIN = 220


def norm(w: str) -> str:
    w = w.lower().replace('ё', 'е')
    return re.sub(r'[^\w]+', ' ', w).strip()


def hms(t: float) -> str:
    t = max(0, int(t))
    return f'{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}'


CARD_SPLITS = []
TM_EXTRA = {}   # duration_s / chapters of the final timemap (materials/text_build/build_final_timemap.py)


def load_timemap(path):
    if path:
        tm = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
        segs = tm['segments'] if isinstance(tm, dict) else tm
        if isinstance(tm, dict):
            TM_EXTRA.update({k: tm[k] for k in ('duration_s', 'chapters') if k in tm})
    else:
        tl = json.loads((JOB / 'timeline.json').read_text(encoding='utf-8'))
        segs = [{'source': s['source'], 'src_in': s['src_in'], 'src_out': s['src_out'], 'edit_in': s['edit_in']}
                for s in tl['segments'] if s.get('recommended')]
    segs = sorted(segs, key=lambda s: s['edit_in'])
    return segs


def to_edit(segs, source, t):
    for s in segs:
        if s['source'] == source and s['src_in'] <= t < s['src_out']:
            return s['edit_in'] + (t - s['src_in'])
    return None


def load_words(segs):
    """All kept words in edit order: dict(source, src_t, t (edit), end, word, text, speaker)."""
    out = []
    for source, path in SOURCES.items():
        data = json.loads(path.read_text(encoding='utf-8'))
        for w in data['words']:
            t = to_edit(segs, source, w['start'])
            if t is None:
                continue
            out.append({'source': source, 'src_t': w['start'], 't': t,
                        'end': t + (w['end'] - w['start']), 'word': w['word'],
                        'text': w['punctuated_word'], 'speaker': w.get('speaker') or '',
                        'filler': bool(w.get('filler')) or norm(w['word']) in FILLERS})
    out.sort(key=lambda w: w['t'])
    return out


def resolve_chapters(words, chapters):
    """Phrase anchor -> index of the first word of the sentence that contains it."""
    seq = [(i, norm(w['word'])) for i, w in enumerate(words) if not w['filler']]
    res = []
    for ch in chapters:
        if 'card_n' in ch['anchor']:
            # final video chapter card: the chapter starts at the first kept word after the card
            cards = {c.get('card_n'): c['final_start_s'] for c in TM_EXTRA.get('chapters', [])}
            if ch['anchor']['card_n'] not in cards:
                sys.exit(f'chapter card {ch["anchor"]} needs --timemap with chapters (build_final_timemap.py)')
            # the card sits in a 3.6 s gap between pieces: +1 s skips a word that straddles the cut before it
            t0 = cards[ch['anchor']['card_n']] + 1.0
            hit = next((i for i, w in enumerate(words) if w['t'] >= t0 and not w['filler']), None)
            if hit is None:
                sys.exit(f'no words after chapter card {ch["anchor"]}')
            # a card can split a sentence: keep the sentence whole on the side where most of it is
            head, j = 0, hit - 1
            while j >= 0 and not TERMINAL.search(words[j]['text']) and head < 40:
                head += not words[j]['filler']; j -= 1
            if head:
                tail, k = 0, hit
                while k < len(words) and tail < 40:
                    tail += not words[k]['filler']
                    if TERMINAL.search(words[k]['text']):
                        break
                    k += 1
                # a short head (≤3 words: «Здесь сразу же» + card + «хочется сказать про <продукт>») moves forward,
                # otherwise a short tail (≤25 words) goes back to the chapter it finishes
                hit = j + 1 if head <= 3 else (k + 1 if tail <= 25 else j + 1)
                CARD_SPLITS.append({'card_n': ch['anchor']['card_n'], 'head': head, 'tail': tail,
                                    'moved': 'head->next' if hit == j + 1 else 'tail->prev'})
            res.append(hit)
            continue
        src = ch['anchor']['source']
        toks = norm(ch['anchor']['phrase']).split()
        hit = None
        for k in range(len(seq) - len(toks) + 1):
            i0 = seq[k][0]
            if words[i0]['source'] != src:
                continue
            got = ' '.join(t for _, t in seq[k:k + len(toks) * 2])
            if ' '.join(t for _, t in seq[k:k + len(toks)]) == ' '.join(toks) or got.startswith(' '.join(toks)):
                hit = i0
                break
        if hit is None:
            sys.exit(f'chapter anchor not found: {ch["title"]!r} / {ch["anchor"]}')
        i = hit
        for _ in range(60):  # back up to the sentence start
            j = i - 1
            if j < 0 or TERMINAL.search(words[j]['text']) or words[j]['speaker'] != words[hit]['speaker']:
                break
            i = j
        res.append(i)
    if res != sorted(res):
        sys.exit(f'chapter anchors are not in order: {res}')
    return res


def speaker_id(name):
    if name.startswith('Видео'):
        return 'video'
    return SPEAKERS.get(name, 'guest')


def build_paragraphs(words, ch_starts):
    ch_at = {i: n for n, i in enumerate(ch_starts)}
    paras, cur = [], None
    chapter = 0

    def flush():
        nonlocal cur
        if cur and cur['toks']:
            paras.append(cur)
        cur = None

    for i, w in enumerate(words):
        if i in ch_at:
            flush()
            chapter = ch_at[i]
        sid = speaker_id(w['speaker'])
        label = w['speaker'].split(':', 1)[1].strip() if sid == 'video' and ':' in w['speaker'] else ''
        if cur and (sid != cur['speaker'] or (sid == 'video' and label != cur['label'])):
            flush()
        if cur:
            length = sum(len(x) + 1 for x in cur['toks'])
            prev = cur['last_text']
            gap = w['t'] - cur['last_end']
            if TERMINAL.search(prev) and (length >= SOFT_MAX or (gap >= GAP_BREAK and length >= SOFT_MIN)):
                flush()
            elif length >= HARD_MAX and prev.endswith(','):
                flush()
        if cur is None:
            cur = {'t': w['t'], 'src': w['source'], 'src_t': w['src_t'], 'speaker': sid, 'label': label,
                   'chapter': chapter, 'toks': [], 'last_text': '', 'last_end': w['t'], 'n_words': 0}
        if w['filler']:
            # keep sentence punctuation carried by a dropped filler
            m = re.search(r'[.?!…]$', w['text'])
            if m and cur['toks'] and not re.search(r'[.?!…,:;]$', cur['toks'][-1]):
                cur['toks'][-1] += m.group(0)
            cur['last_end'] = w['end']
            continue
        text = w['text']
        if not cur['toks'] or TERMINAL.search(cur['toks'][-1]):
            text = text[:1].upper() + text[1:]
        cur['toks'].append(text)
        cur['last_text'] = text
        cur['last_end'] = w['end']
        cur['n_words'] += 1
    flush()
    for p in paras:
        txt = ' '.join(p.pop('toks'))
        txt = re.sub(r'\s+([,.!?…:;])', r'\1', txt)
        txt = re.sub(r',([.?!…])', r'\1', txt)
        txt = re.sub(r'\s{2,}', ' ', txt).strip()
        if txt and txt[-1] not in '.?!…':
            txt = txt.rstrip(',;:') + '.'
        p['text'] = txt
        p.pop('last_text'); p.pop('last_end')
    return paras


def apply_redactions(paras, rules):
    log = []
    for r in rules:
        rx = re.compile(r['pattern'])
        hits = 0
        for p in paras:
            p['text'], n = rx.subn(r['replace'], p['text'])
            if n:
                hits += n
                log.append({'id': r['id'], 'tc': hms(p['t']), 'n': n})
        if hits < r.get('expect', 0):
            sys.exit(f'redaction {r["id"]} expected >= {r["expect"]} hits, got {hits} — check the source text')
        r['hits'] = hits
    return log


# Light editing of speech paragraphs (after redactions): filler words and stutter repeats out, meaning kept.
# Each rule is conservative: a filler is dropped only where commas/sentence ends isolate it.
ASR_FIXES_REFERENCE = [  # (pattern, replacement, min hits) — obvious recognition errors, checked by context
    (r'\bТюринг', 'Тьюринг', 2),
    (r'Когда у продукта нет AI, да,', 'Когда у продукта нет API,', 1),
]
# job-specific recognition fixes live in data/transcript_asr_fixes.json {"fixes": [[pattern, replacement, min_hits]]};
# the list above is the reference run's, kept as an example of the format
_fx = ROOT / 'data/transcript_asr_fixes.json'
ASR_FIXES = [tuple(x) for x in json.loads(_fx.read_text(encoding='utf-8'))['fixes']] if _fx.exists() else []
LIGHT = [
    (r'(?:(?<=^)|(?<=[.?!…] ))(?:Вот|Ага|Угу|Так)\. ', ''),          # standalone «Вот.» «Ага.»
    (r'(?:(?<=^)|(?<=[.?!…] ))(?:Вот|Ну вот|Так вот), ', ''),         # sentence-initial «Вот, …»
    (r', Вот(?=[.?!…])', ''),                                         # «…получились, Вот.»
    (r',? (?:вот|ага|угу)(?=[,.?!…])', ''),                           # pure fillers before a comma / sentence end
    (r', (?:да|ну|как бы|собственно|в общем|так сказать|типа|вот там|там вот)(?=[,.?!…])', ''),  # isolated by commas
    (r', там(?=,)(?!, (?:где|куда|откуда|когда))', ''),               # «, там,» but keep «там, где»
    (r'(?<=[,:]) вот(?= )', ''),                                      # «, вот что…» -> «, что…»
]
REPEAT = re.compile(r'\b(\w+(?: \w+){0,2}),? \1\b(?![-\w])', re.IGNORECASE)


def light_edit(text):
    for rx, rep in LIGHT:
        text = re.sub(rx, rep, text)
    text = REPEAT.sub(r'\1', text)
    text = re.sub(r'\s+([,.?!…:;])', r'\1', text)
    text = re.sub(r',{2,}', ',', text)
    text = re.sub(r',([.?!…])', r'\1', text)
    text = re.sub(r'^[,\s]+', '', text)
    # capitalise sentence starts again
    text = re.sub(r'(^|[.?!…] )([а-яёa-z])', lambda m: m.group(1) + m.group(2).upper(), text)
    return text.strip()


def apply_light_edit(paras):
    fixes = []
    for rx, rep, expect in ASR_FIXES:
        hits = 0
        for p in paras:
            p['text'], n = re.subn(rx, rep, p['text'])
            hits += n
        if hits < expect:
            sys.exit(f'ASR fix {rx!r} expected >= {expect} hits, got {hits}')
        fixes.append({'pattern': rx, 'hits': hits})
    before = sum(len(p['text'].split()) for p in paras if p['kind'] == 'speech')
    for p in paras:
        if p['kind'] == 'speech' and p['text']:
            p['text'] = light_edit(p['text'])
    after = sum(len(p['text'].split()) for p in paras if p['kind'] == 'speech')
    return {'asr_fixes': fixes, 'speech_words_before': before, 'speech_words_after': after}


def merge_video(paras):
    """Short playback fragments (a few English words etc.) become one note; long ones stay as quotes."""
    out = []
    for p in paras:
        if p['speaker'] == 'video':
            if out and out[-1]['speaker'] == 'video' and out[-1]['label'] == p['label']:
                out[-1]['text'] += ' ' + p['text']; out[-1]['n_words'] += p['n_words']
                continue
        out.append(p)
    for p in out:
        if p['speaker'] == 'video':
            p['kind'] = 'video'
            if p['n_words'] < 15:
                p['text'] = ''
        else:
            p['kind'] = 'speech'
    return out


def merge_tiny(paras, max_words=2):
    """Fold one- or two-word speech paragraphs («Вот.») into the neighbour of the same speaker and chapter."""
    out = []
    for p in paras:
        if (p['kind'] == 'speech' and p['n_words'] <= max_words and out and out[-1]['kind'] == 'speech'
                and out[-1]['speaker'] == p['speaker'] and out[-1]['chapter'] == p['chapter']):
            out[-1]['text'] += ' ' + p['text']; out[-1]['n_words'] += p['n_words']
            continue
        out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--timemap', help='final EDL as {"segments":[{source,src_in,src_out,edit_in}]}; default = timeline.json (provisional)')
    ap.add_argument('--final', action='store_true', help='mark timecodes as final (clears the provisional banner)')
    ap.add_argument('--doc', default=str(ROOT / 'data/transcript_doc.json'), help='cover/meta texts')
    ap.add_argument('--out', default=str(ROOT / 'data/transcript.data.json'))
    a = ap.parse_args()
    SPEAKERS.update({v['name']: k for k, v in json.loads(pathlib.Path(a.doc).read_text(encoding='utf-8')).get('speakers', {}).items()
                     if k not in ('video', 'guest')})

    segs = load_timemap(a.timemap)
    words = load_words(segs)
    chapters = json.loads((ROOT / 'data/transcript_chapters.json').read_text(encoding='utf-8'))['chapters']
    starts = resolve_chapters(words, chapters)
    paras = merge_tiny(merge_video(build_paragraphs(words, starts)))
    rules = json.loads((ROOT / 'data/transcript_redactions.json').read_text(encoding='utf-8'))['redactions']
    red_log = apply_redactions(paras, rules)
    edit_log = apply_light_edit(paras)
    paras = [p for p in paras if p['kind'] != 'speech' or p['text']]

    doc = json.loads(pathlib.Path(a.doc).read_text(encoding='utf-8'))
    total = round(TM_EXTRA.get('duration_s') or 0) or max(s['edit_in'] + s['src_out'] - s['src_in'] for s in segs)
    ch_out = []
    for n, (ch, i) in enumerate(zip(chapters, starts)):
        # chapter time = the chapter card in the video (same as the RuTube timecodes), else the first word
        cards = {c.get('card_n'): c['final_start_s'] for c in TM_EXTRA.get('chapters', [])}
        ct = cards.get(ch['anchor'].get('card_n', -1), words[i]['t'])
        ch_out.append({'n': n + 1, 'title': ch['title'], 'lead': ch.get('lead', ''), 'art': ch['art'],
                       'theme': ch['theme'], 't': round(ct, 2), 'tc': hms(round(ct) if ch['anchor'].get('card_n') else ct),
                       'card_t': next((c['final_start_s'] for c in TM_EXTRA.get('chapters', []) if c.get('card_n') == ch['anchor'].get('card_n', -1)), None),
                       'anchor_src': {'source': words[i]['source'], 'src_t': words[i]['src_t']}})
    out_paras = [{'t': round(p['t'], 2), 'tc': hms(p['t']), 'chapter': p['chapter'] + 1, 'speaker': p['speaker'],
                  'kind': p['kind'], 'label': p['label'], 'text': p['text']} for p in paras]
    # the first paragraph of a card chapter never shows a time before its card (head words moved forward)
    for c in ch_out:
        if c.get('card_t') is not None:
            first = next((p for p in out_paras if p['chapter'] == c['n']), None)
            if first and first['t'] < c['card_t'] + 3.6:
                first['t'], first['tc'] = max(first['t'], c['t']), c['tc'] if first['t'] < c['card_t'] + 1.0 else first['tc']
    n_words = sum(len(p['text'].split()) for p in out_paras)
    data = {
        'contract': 'transcript/v1',
        'meta': {
            'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'generator': str(pathlib.Path(__file__).resolve()),
            'timecodes': 'final' if a.final else 'provisional',
            'timemap': a.timemap or str(JOB / 'timeline.json') + ' (recommended segments)',
            'duration_s': round(total, 1), 'duration_hms': hms(total),
            'paragraphs': len(out_paras), 'words': n_words,
            'redactions': [{k: r[k] for k in ('id', 'reason', 'hits')} for r in rules],
            'redaction_log': red_log,
            'light_edit': edit_log,
            'card_splits': CARD_SPLITS,
        },
        'doc': doc,
        'speakers': doc.get('speakers', {}),
        'chapters': ch_out,
        'paragraphs': out_paras,
    }
    pathlib.Path(a.out).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'out': a.out, 'timecodes': data['meta']['timecodes'], 'duration': hms(total),
                      'chapters': [(c['tc'], c['title']) for c in ch_out], 'paragraphs': len(out_paras),
                      'words': n_words, 'redactions': {r['id']: r['hits'] for r in rules}}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
