"""S14: LIGHT literary edit of a Russian live-speech transcript (the words of the speakers stay theirs).

Only what a reader never misses: standalone fillers («Вот.», «Ага.»), fillers isolated by commas («, да,», «, ну,»,
«, как бы,»), sentence-initial «Вот,» / «Так вот,», stutter repeats («как, как» -> «как», up to 3-word groups),
spaces before punctuation, doubled commas, sentence capitals. «там, где» is kept. Reference run: -4.3 % words.
Plus obvious ASR fixes from a job file [[pattern, replacement, min_hits]] - the run FAILS when a fix finds fewer hits
than expected (the text changed upstream; review instead of silently skipping).

The same functions are built into templates/pdf-materials/build_transcript_data.py (paragraphs of the PDF transcript).
usage: python light_edit.py <in.txt> <out.txt> [--fixes transcript_asr_fixes.json]      (UTF-8, paragraph per line)
"""
import json
import re
import sys

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
    text = re.sub(r'(^|[.?!…] )([а-яёa-z])', lambda m: m.group(1) + m.group(2).upper(), text)  # sentence starts
    return text.strip()


def apply_fixes(paras, fixes):
    log = []
    for rx, rep, expect in fixes:
        n = 0
        for i, p in enumerate(paras):
            paras[i], k = re.subn(rx, rep, p)
            n += k
        if n < expect:
            raise SystemExit(f'ASR fix {rx!r} hit {n} < {expect}: the text changed, review the fix')
        log.append({'pattern': rx, 'hits': n})
    return log


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    paras = open(sys.argv[1], encoding='utf-8').read().split('\n')
    fixes = []
    if '--fixes' in sys.argv:
        fixes = [tuple(x) for x in json.load(open(sys.argv[sys.argv.index('--fixes') + 1], encoding='utf-8'))['fixes']]
    log = apply_fixes(paras, fixes)
    w0 = sum(len(p.split()) for p in paras)
    out = [light_edit(p) if p.strip() else p for p in paras]
    w1 = sum(len(p.split()) for p in out)
    with open(sys.argv[2], 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(out))
    print(json.dumps({'words_in': w0, 'words_out': w1, 'removed_pct': round(100 * (w0 - w1) / max(1, w0), 1), 'fixes': log}, ensure_ascii=False))


if __name__ == '__main__':
    main()
