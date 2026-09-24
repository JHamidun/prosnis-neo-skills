"""S14: rebuild EVERY text material from the current montage EDL - run it again whenever edl/edl.json changes
(a re-cut moves every timecode; the reference run rebuilt after each EDL fix).

1. build_final_timemap.py      edl/edl.json + edl/chapters.json -> materials/final_timemap.json
2. build_transcript_data.py    words + timemap -> materials/pdf_templates/data/transcript.data.json (final timecodes)
3. make_text_materials.py      -> transcript_clean.md, timecodes.txt, summary.md, rutube_meta.json
4. render_pdf.py x2            -> the transcript and summary PDFs (--drop-pending-links while {EVENT_PAGE_LINK}/{PDF_LINK}
                                  are not filled)
5. PNG proofs                  -> materials/pdf_preview/*.png (look at them)

The PDF templates live in <job>/materials/pdf_templates (copy of templates/pdf-materials).
usage: python rebuild_all.py --job job.json [--pdf-link https://…] [--event-link https://…]
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
HERE = Path(__file__).resolve().parent
MAT = Path(J.p('materials'))
TPL = MAT / 'pdf_templates'
os.environ['PYTHONIOENCODING'] = 'utf-8'


def run(args, cwd):
    print('>', ' '.join(map(str, args)), flush=True)
    r = subprocess.run([sys.executable, *map(str, args), '--job', str(J.file)], cwd=cwd)
    if r.returncode:
        sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf-link')
    ap.add_argument('--event-link')
    a = ap.parse_args()
    run([HERE / 'build_final_timemap.py'], HERE)
    if a.pdf_link or a.event_link:  # fills {EVENT_PAGE_LINK}/{PDF_LINK} in data/{shared,transcript_doc}.json in place
        sys.path.insert(0, str(TPL))
        import make_all
        make_all.fill_links(a.event_link, a.pdf_link)
    run(['build_transcript_data.py', '--timemap', MAT / 'final_timemap.json', '--final'], TPL)
    run([HERE / 'make_text_materials.py'], HERE)
    pending = any('{' in (TPL / f).read_text(encoding='utf-8') and 'LINK}' in (TPL / f).read_text(encoding='utf-8')
                  for f in ('data/shared.json', 'data/transcript_doc.json'))
    names = J.get('materials.pdf_names') or {'transcript': f"Transcript_{J.get('job', 'webinar')}", 'summary': f"Summary_{J.get('job', 'webinar')}"}
    for kind in ('transcript', 'summary'):
        run(['render_pdf.py', kind, '--final', *(['--drop-pending-links'] if pending else []), '--out', MAT / f'{names[kind]}.pdf'], TPL)
    import fitz
    (MAT / 'pdf_preview').mkdir(exist_ok=True)
    for kind, pages in (('transcript', (1, 2, 4)), ('summary', (1, 2, 7))):
        d = fitz.open(str(MAT / f'{names[kind]}.pdf'))
        for n in pages:
            if n <= len(d):
                d[n - 1].get_pixmap(dpi=100).save(str(MAT / 'pdf_preview' / f'{kind}_p{n:02d}.png'))
        print(names[kind], len(d), 'pages')
    print('links pending (hidden in PDFs):', pending)


if __name__ == '__main__':
    main()
