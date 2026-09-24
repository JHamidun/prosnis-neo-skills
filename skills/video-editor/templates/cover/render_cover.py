"""Render the video covers from cover.html: Tilda/site 1200x675 PNG + WebP q90 (both QR codes) and RuTube 1280x720
(Telegram QR only, kept clear of the duration badge RuTube draws in the bottom-right corner).

HTML + CSS vars -> Playwright headless through a local HTTP server -> PNG at device scale 2 (2400x1350), downsampled with
Lanczos for crisp text. The QR codes are DECODED back from the output as the check (cv2 on a x4 upscale of the QR area -
at 1x it misses 60-70 px codes). Fonts (Manrope 800), the QR library and every image must load, or the run fails.

Folder layout (copy this template dir to <job>/materials/cover/):
  cover.html, cover.json (texts/links, see cover.example.json), assets/: speaker cutout <name>.png + rim_<name>.png
  (cutout.py), brand mark h_logo.png, decorative pngs referenced by the HTML (pills of the reference design).
usage: python render_cover.py [--config cover.json] [--theme canon|vibe] [--speaker speaker_1234.50.png]
                              [--rutube-url https://rutube.ru/video/<id>/] [--suffix _x] [--out DIR] [--port 8767]
Re-run with --rutube-url once the video is on RuTube so the QR points at the video, not the channel.
"""
import argparse
import html as H
import http.server
import json
import re
import socketserver
import threading
from pathlib import Path

import cv2
from PIL import Image

HERE = Path(__file__).resolve().parent


class Server(threading.Thread):
    def __init__(self, root, port):
        super().__init__(daemon=True)
        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(root), **kw)  # noqa: E731
        http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
        self.httpd = socketserver.TCPServer(("127.0.0.1", port), handler)

    def run(self):
        self.httpd.serve_forever()


def decode_qrs(png):
    img = cv2.imread(str(png))
    h, w = img.shape[:2]
    crop = cv2.resize(img[int(h * 0.76):h, int(w * 0.55):w], None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    ok, texts, _, _ = cv2.QRCodeDetector().detectAndDecodeMulti(crop)
    return sorted(t for t in (texts if ok else []) if t)


def fill(tpl, cfg, speaker, rutube_url):
    """cover.json -> placeholders; title_html may contain <span class="hl">accent</span> and <br>."""
    css = {'category': cfg.get('category', 'ВЕБИНАР'), 'subtitle': cfg.get('subtitle', ''), 'date': cfg.get('date', ''),
           'duration': cfg.get('duration', ''), 'speaker_role': cfg.get('speaker_role', ''), 'rutube_url': rutube_url,
           'tg_url': cfg['tg_url']}
    for k, v in css.items():
        tpl = tpl.replace(f'__{k.upper()}__', str(v).replace('"', '\\"'))
    tags = ''.join(f'\n        <span class="tag">{H.escape(t)}</span>' for t in cfg.get('tags', [])) + '\n      '
    tpl = (tpl.replace('__TITLE_HTML__', cfg['title_html']).replace('__TAGS_HTML__', tags)
           .replace('__SPEAKER_NAME__', H.escape(cfg['speaker_name'])).replace('__TG_LABEL__', H.escape(cfg.get('tg_label', '')))
           .replace('__WORDMARK__', H.escape(cfg.get('wordmark', ''))))
    tpl = tpl.replace('__SPEAKER__', speaker).replace('__RIM__', 'rim_' + speaker)
    left = re.findall(r'__[A-Z_]+__', tpl)
    if left:
        raise SystemExit(f'unfilled placeholders: {sorted(set(left))}')
    return tpl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'cover.json'))
    ap.add_argument('--theme', default='canon', choices=['canon', 'vibe'])
    ap.add_argument('--speaker')
    ap.add_argument('--rutube-url')
    ap.add_argument('--suffix', default='')
    ap.add_argument('--out', default=str(HERE.parent))
    ap.add_argument('--port', type=int, default=8767)
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding='utf-8'))
    speaker = a.speaker or cfg['speaker_png']
    rutube_url = a.rutube_url or cfg['rutube_url']
    page_file = HERE / f"_render{a.suffix or '_' + a.theme}.html"
    page_file.write_text(fill((HERE / 'cover.html').read_text(encoding='utf-8'), cfg, speaker, rutube_url), encoding='utf-8', newline='\n')
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    srv = Server(HERE, a.port)
    srv.start()
    from playwright.sync_api import sync_playwright
    raws = {}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            for platform in ('tilda', 'rutube'):
                page = b.new_context(viewport={'width': 1200, 'height': 675}, device_scale_factor=2).new_page()
                q = f'?platform={platform}' + ('&theme=vibe' if a.theme == 'vibe' else '')
                page.goto(f'http://127.0.0.1:{a.port}/{page_file.name}{q}')
                page.wait_for_load_state('networkidle')
                page.evaluate('document.fonts.ready')
                state = page.evaluate("""() => ({
                    manrope: document.fonts.check('800 58px Manrope'),
                    qr: document.body.dataset.qr,
                    imgs: [...document.images].map(i => [i.src.split('/').pop(), i.complete && i.naturalWidth > 0]),
                })""")
                print(platform, json.dumps(state, ensure_ascii=False))
                assert state['manrope'], 'Manrope did not load'
                assert state['qr'] == 'ok', 'QR library did not load'
                assert all(ok for _, ok in state['imgs']), f"image failed: {state['imgs']}"
                raws[platform] = HERE / f'raw_2x_{platform}{a.suffix}.png'
                page.locator('#cover').screenshot(path=str(raws[platform]))
                page.context.close()
            b.close()
    finally:
        srv.httpd.shutdown()
    tilda = out / f'cover_tilda{a.suffix}.png'
    rutube = out / f'cover_rutube{a.suffix}.png'
    Image.open(raws['tilda']).convert('RGB').resize((1200, 675), Image.LANCZOS).save(tilda, optimize=True)
    Image.open(raws['rutube']).convert('RGB').resize((1280, 720), Image.LANCZOS).save(rutube, optimize=True)
    Image.open(tilda).save(out / f'cover_tilda{a.suffix}.webp', 'WEBP', quality=90, method=6)
    for f, want in ((tilda, sorted([cfg['tg_url'], rutube_url])), (rutube, [cfg['tg_url']])):
        got = decode_qrs(f)
        print(f, Image.open(f).size, f'{f.stat().st_size // 1024} KB', 'QR:', got)
        assert got == want, f'QR check failed for {f}: {got} != {want}'
    print('webp', (out / f'cover_tilda{a.suffix}.webp').stat().st_size // 1024, 'KB')


if __name__ == '__main__':
    main()
