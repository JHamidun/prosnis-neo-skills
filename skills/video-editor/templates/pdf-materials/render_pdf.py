"""Render the branded A4 PDFs (summary / transcript) from HTML template + JSON data.

    python render_pdf.py transcript                     # preview: data/transcript.data.json -> out/…_ЧЕРНОВИК.pdf
    python render_pdf.py summary
    python render_pdf.py summary --final --out "…/Саммари_<slug>.pdf"

Steps: merge data (+ data/shared.json, art sizes, transcript chapters for the summary) -> lint the text
(placeholders, contacts, owner's wording rules) -> inject JSON into the template -> headless Chromium
page.pdf (A4, CSS page size, backgrounds) -> PDF metadata -> PNG proofs of every page in _qa/<kind>/.
--final refuses to render if a {PLACEHOLDER} is left or transcript timecodes are provisional.
"""
import argparse, datetime, json, os, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent
from _job import JOB, get  # noqa: E402  (sets TEMP/TMP to <job>/tmp)

TITLES = {'summary': 'Саммари', 'transcript': 'Транскрипт'}

# Lint rules (regex, message, applies_to). Generic defaults = contacts and sums. The owner's own wording rules
# (forbidden claims, product naming, topics kept out of public texts) live in job.json materials.rules
# [["regex", "message", ["summary", "transcript"]], ...] (applies_to omitted = summary only) and are ADDED to these.
DEFAULT_RULES = [
    (r'[\w.+-]+@[\w-]+\.[\w.]+', 'e-mail в тексте', ('summary', 'transcript')),
    (r'(?<!\d)(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)', 'телефон в тексте', ('summary', 'transcript')),
    (r'\d[\d\s]*(?:₽|руб\w*|\$|долл\w*)', 'цена/сумма — проверьте, что это не цена вашего продукта', ('summary',)),
]


def job_rule(r):
    """job.json rule [regex, message] or [regex, message, kind | [kinds]] -> (regex, message, applies_to)."""
    sc = r[2] if len(r) > 2 else None
    return r[0], r[1], (sc,) if isinstance(sc, str) else tuple(sc or ('summary',))


RULES = DEFAULT_RULES + [job_rule(r) for r in get('materials.rules', []) or []]
# links allowed in the PDFs (owner's rule: only the bot and the host's Telegram; the rest via {PLACEHOLDER}s)
ALLOWED_URL_HOSTS = tuple(json.loads((ROOT / 'data/shared.json').read_text(encoding='utf-8')).get('allowed_url_hosts', [])) \
    if (ROOT / 'data/shared.json').exists() else ()


def strings(o, path=''):
    if isinstance(o, dict):
        for k, v in o.items():
            if not str(k).startswith('$'):
                yield from strings(v, f'{path}.{k}')
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from strings(v, f'{path}[{i}]')
    elif isinstance(o, str):
        yield path, o


def lint(kind, data):
    warns, placeholders = [], set()
    for path, s in strings(data):
        if path.startswith(('.meta', '.art_sizes', '.art_ink')):
            continue
        placeholders.update(re.findall(r'\{[A-Z_]+\}', s))
        for rx, msg, scope in RULES:
            if kind in scope:
                for m in re.finditer(rx, s):
                    ctx = s[max(0, m.start() - 40): m.end() + 40].replace('\n', ' ')
                    warns.append(f'{msg}: {path}: …{ctx}…')
        for m in re.finditer(r'https?://[^\s"<>]+|t\.me/[\w/]+', s):
            if not any(h in m.group(0) for h in ALLOWED_URL_HOSTS):
                warns.append(f'ссылка вне белого списка: {path}: {m.group(0)}')
    return warns, sorted(placeholders)


def drop_pending(o):
    """Blank every string that is exactly one {PLACEHOLDER} (a link that is not published yet)."""
    if isinstance(o, dict):
        return {k: drop_pending(v) for k, v in o.items()}
    if isinstance(o, list):
        return [drop_pending(v) for v in o]
    if isinstance(o, str) and re.fullmatch(r'\{[A-Z_]+\}', o):
        return ''
    return o


def load(kind, data_path):
    data = json.loads(pathlib.Path(data_path).read_text(encoding='utf-8'))
    data['shared'] = json.loads((ROOT / 'data/shared.json').read_text(encoding='utf-8'))
    man = json.loads((ROOT / 'assets/art/manifest.json').read_text(encoding='utf-8'))
    data['art_sizes'] = {k: v['size'] for k, v in man.items()}
    data['art_ink'] = {k: v['ink'] for k, v in man.items()}
    if kind == 'summary':
        tr = json.loads((ROOT / 'data/transcript.data.json').read_text(encoding='utf-8'))
        if data.get('chapters') == '@transcript':
            data['chapters'] = [{k: c[k] for k in ('n', 'title', 'lead', 'tc', 't')} for c in tr['chapters']]
        data.setdefault('meta', {})['timecodes'] = tr['meta']['timecodes']
        data['meta']['duration_s'] = tr['meta']['duration_s']
        data['meta']['duration_hms'] = tr['meta']['duration_hms']
    return data


def render(kind, data, out_pdf):
    from playwright.sync_api import sync_playwright
    tpl = (ROOT / f'{kind}.html').read_text(encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    assert '/*__DATA__*/' in tpl
    # running header of every page = job.json brand.header (e.g. the school name in capitals)
    html = tpl.replace('/*__DATA__*/', payload).replace('__BRAND_HEADER__', str(get('brand.header', '')).replace('"', ''))
    html = html.replace('__DOC_TITLE__', str((data.get('doc') or {}).get('title', '')).replace('"', ''))  # <title> + running header
    build = ROOT / f'_build_{kind}.html'   # must live next to the template: assets/ are relative
    build.write_text(html, encoding='utf-8')
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        pg.goto(build.as_uri())
        pg.wait_for_function('window.__RENDER_DONE__', timeout=60000)
        done = pg.evaluate('window.__RENDER_DONE__')
        fonts = pg.evaluate("['800 20px Manrope','400 12px Manrope','500 10px \"JetBrains Mono\"','600 16px Caveat'].map(f=>document.fonts.check(f))")
        if errors or done.get('broken') or not all(fonts):
            b.close()
            sys.exit(f'render problems: js={errors} broken_images={done.get("broken")} fonts={fonts}')
        kw = dict(path=str(out_pdf), prefer_css_page_size=True, print_background=True)
        try:
            pg.pdf(**kw, tagged=True, outline=True)
        except TypeError:
            pg.pdf(**kw)
        b.close()
    return done


def finish(kind, data, out_pdf, png_dir, dpi):
    import fitz
    d = fitz.open(str(out_pdf))
    doc = data.get('doc', {})
    d.set_metadata({'title': f'{doc.get("title", "")} — {TITLES[kind].lower()} эфира {doc.get("date", "")}'.strip(),
                    'author': get('author', doc.get('host', '')), 'subject': doc.get('subtitle', ''),
                    'creator': get('brand.name', ''), 'producer': 'render_pdf.py (Chromium)',
                    'keywords': ', '.join(get('materials.keywords', []) or [])})
    # Chromium builds the outline from laid-out lines and drops the space at a line wrap
    # («синяятаблетка»): restore titles from the data by whitespace-insensitive match
    known = {re.sub(r'\s+', '', s): s for _, s in strings(data) if 3 < len(s) < 160}
    toc = d.get_toc()
    for e in toc:
        e[1] = known.get(re.sub(r'\s+', '', e[1]), e[1])
    if toc:
        d.set_toc(toc)
    tmp = out_pdf.with_suffix('.tmp.pdf')
    d.save(str(tmp), garbage=3, deflate=True)
    d.close()
    tmp.replace(out_pdf)
    d = fitz.open(str(out_pdf))
    png_dir.mkdir(parents=True, exist_ok=True)
    for f in png_dir.glob('p*.png'):
        f.unlink()
    links = 0
    for i, page in enumerate(d):
        page.get_pixmap(dpi=dpi).save(str(png_dir / f'p{i + 1:03d}.png'))
        links += len(page.get_links())
    info = {'pages': len(d), 'links': links, 'size_mb': round(out_pdf.stat().st_size / 1e6, 2)}
    d.close()
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('kind', choices=['summary', 'transcript'])
    ap.add_argument('--data')
    ap.add_argument('--out')
    ap.add_argument('--final', action='store_true')
    ap.add_argument('--dpi', type=int, default=60)
    ap.add_argument('--drop-pending-links', action='store_true',
                    help='links that do not exist yet: a URL field that is exactly a {PLACEHOLDER} becomes empty and its item is hidden')
    a = ap.parse_args()
    data_path = a.data or ROOT / f'data/{a.kind}.data.json'
    data = load(a.kind, data_path)
    if a.drop_pending_links:
        data = drop_pending(data)
    warns, ph = lint(a.kind, data)
    provisional = data.get('meta', {}).get('timecodes') != 'final'
    if a.final and (ph or provisional):
        sys.exit(f'--final refused: placeholders={ph} provisional_timecodes={provisional}')
    base = get(f'materials.pdf_names.{a.kind}') or f"{TITLES[a.kind]}_{get('job', 'webinar')}"
    name = base + ('' if a.final else '_ЧЕРНОВИК')
    out = pathlib.Path(a.out) if a.out else ROOT / 'out' / f'{name}.pdf'
    out.parent.mkdir(parents=True, exist_ok=True)
    done = render(a.kind, data, out)
    info = finish(a.kind, data, out, ROOT / '_qa' / a.kind, a.dpi)
    report = {'out': str(out), **info, 'images': done.get('images'), 'placeholders_left': ph,
              'timecodes': 'provisional' if provisional else 'final', 'lint_warnings': warns,
              'rendered_at': datetime.datetime.now().isoformat(timespec='seconds')}
    (ROOT / '_qa' / f'{a.kind}.render.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
