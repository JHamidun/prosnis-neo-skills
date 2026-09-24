"""One command for both PDFs.

Preview (provisional timecodes from timeline.json, placeholders allowed):
    python make_all.py
Final (after the montage EDL is fixed and the links exist):
    python make_all.py --job <job.json> --timemap <job>/materials/final_timemap.json \
        --event-link https://… --pdf-link https://… --final --outdir <job>/publish/materials
Output names: job.json materials.pdf_names {"transcript": "Транскрипт_<slug>", "summary": "Саммари_<slug>"}
"""
import argparse, json, pathlib, subprocess, sys

from _job import get

ROOT = pathlib.Path(__file__).resolve().parent


def run(*args):
    print('>', ' '.join(map(str, args)), flush=True)
    r = subprocess.run([sys.executable, *map(str, args)], cwd=ROOT)
    if r.returncode:
        sys.exit(r.returncode)


def fill_links(event, pdf):
    """Replace {EVENT_PAGE_LINK}/{PDF_LINK} in shared.json and transcript_doc.json (in place)."""
    for name in ('data/shared.json', 'data/transcript_doc.json'):
        p = ROOT / name
        s = p.read_text(encoding='utf-8')
        if event:
            s = s.replace('{EVENT_PAGE_LINK}', event)
        if pdf:
            s = s.replace('{PDF_LINK}', pdf)
        json.loads(s)
        p.write_text(s, encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--timemap')
    ap.add_argument('--final', action='store_true')
    ap.add_argument('--event-link')
    ap.add_argument('--pdf-link')
    ap.add_argument('--outdir')
    ap.add_argument('--drop-pending-links', action='store_true', help='render now, hiding links that are still {PLACEHOLDER}s')
    a = ap.parse_args()
    if a.event_link or a.pdf_link:
        fill_links(a.event_link, a.pdf_link)
    run('build_transcript_data.py', *(['--timemap', a.timemap] if a.timemap else []), *(['--final'] if a.final else []))
    for kind, title in (('transcript', 'Транскрипт'), ('summary', 'Саммари')):
        extra = (['--final'] if a.final else []) + (['--drop-pending-links'] if a.drop_pending_links else [])
        if a.outdir:
            suffix = '' if a.final else '_ЧЕРНОВИК'
            base = (get('materials.pdf_names') or {}).get(kind) or f'{title}_{get("job", "webinar")}'
            extra += ['--out', str(pathlib.Path(a.outdir) / f'{base}{suffix}.pdf')]
        run('render_pdf.py', kind, *extra)


if __name__ == '__main__':
    main()
