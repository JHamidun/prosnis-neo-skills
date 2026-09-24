"""Prepare brand assets for the PDF templates (idempotent, ~10 s).

- crops sketch illustrations out of the deck art (1920x1080, black or cream bg; titles are baked
  into the art, so only illustration regions are cut) and keys the background to alpha,
- writes logo SVG variants for dark and paper backgrounds,
- writes QR codes (navy on transparent) for the links of job.json outro.links[] with "qr": true.
Outputs: assets/art/<name>.png, assets/brand/*.svg, assets/brand/qr-*.png
"""
import json, pathlib, re, numpy as np
from PIL import Image
import qrcode

from _job import get, rel

ROOT = pathlib.Path(__file__).resolve().parent
ART = rel(get('deck.art_dir', 'deck/art'))                 # clean deck art, 1920x1080 PNG per slide
BRAND_SRC = rel(get('brand.dir', 'brand'))                   # brand SVGs (logo for dark bg, coral mark)
LOGO_SVG = get('brand.logo_svg', 'logo-on-dark.svg')
MARK_SVG = get('brand.mark_svg', 'mark.svg')
PAPER = np.array([247, 243, 234], dtype=np.float32)

# name: (source art, crop box x0,y0,x1,y1 in 1920x1080 px) - illustrations cut out of the deck art for the PDFs.
# Job data: data/art_crops.json {"<name>": ["<art file stem>", [x0, y0, x1, y1]]}. Pick boxes on a contact sheet of
# the deck art (titles are baked into the art, so cut only the illustration regions).
_cr = pathlib.Path(__file__).resolve().parent / 'data/art_crops.json'
CROPS = {k: (v[0], tuple(v[1])) for k, v in json.loads(_cr.read_text(encoding='utf-8')).items()} if _cr.exists() else {}
MAX_W = 1100


def key(img: Image.Image, dark: bool) -> tuple[Image.Image, bool]:
    a = np.asarray(img.convert('RGB')).astype(np.float32)
    if dark:  # light strokes on black -> unscreen against black
        v = a.max(axis=2) / 255.0
        alpha = np.clip((v - 0.13) / 0.66, 0, 1)
        col = np.clip(a / np.maximum(v, 1e-3)[..., None], 0, 255)
    else:     # dark ink on cream paper -> unmultiply against paper
        d = ((PAPER - a) / PAPER).max(axis=2)
        alpha = np.clip((d - 0.05) / 0.80, 0, 1)
        col = np.clip((a - PAPER * (1 - alpha[..., None])) / np.maximum(alpha, 1e-3)[..., None], 0, 255)
    h, w = alpha.shape  # feather the crop box so no hard rectangle shows on gradients
    f = 28.0
    ramp_x = np.clip(np.minimum(np.arange(w), np.arange(w)[::-1]) / f, 0, 1)
    ramp_y = np.clip(np.minimum(np.arange(h), np.arange(h)[::-1]) / f, 0, 1)
    alpha = alpha * np.minimum.outer(ramp_y, ramp_x)
    out = np.dstack([col, alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, 'RGBA'), dark


def trim(im: Image.Image, pad=12) -> Image.Image:
    al = np.asarray(im)[..., 3]
    ys, xs = np.where(al > 24)
    if not len(xs):
        return im
    x0, x1, y0, y1 = max(xs.min() - pad, 0), min(xs.max() + pad, im.width), max(ys.min() - pad, 0), min(ys.max() + pad, im.height)
    return im.crop((x0, y0, x1, y1))


def main():
    (ROOT / 'assets/art').mkdir(parents=True, exist_ok=True)
    (ROOT / 'assets/brand').mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, (src, box) in CROPS.items():
        full = Image.open(ART / f'{src}.png').convert('RGB')
        dark = sum(full.getpixel((5, 5))) < 200  # background of the whole slide, not of the crop
        k, dark = key(full.crop(box), dark)
        k = trim(k)
        if k.width > MAX_W:
            k = k.resize((MAX_W, round(k.height * MAX_W / k.width)), Image.LANCZOS)
        k.save(ROOT / 'assets/art' / f'{name}.png', optimize=True)
        manifest[name] = {'src': src, 'box': box, 'ink': 'light' if dark else 'dark', 'size': k.size}
    # logo variants: the source is drawn for dark backgrounds (#FFFFFF / #A9ACC4 text)
    svg = (BRAND_SRC / LOGO_SVG).read_text(encoding='utf-8')
    (ROOT / 'assets/brand/logo-dark-bg.svg').write_text(svg, encoding='utf-8')
    paper = svg.replace('#FFFFFF', '#010334').replace('#A9ACC4', '#5A5E86')
    (ROOT / 'assets/brand/logo-paper-bg.svg').write_text(paper, encoding='utf-8')
    if (BRAND_SRC / MARK_SVG).exists():
        (ROOT / 'assets/brand/mark-coral.svg').write_text((BRAND_SRC / MARK_SVG).read_text(encoding='utf-8'), encoding='utf-8')
    qrs = [(l.get('qr_file') or f"qr-{i}-navy.png", l['url'], l.get('qr_color', '#010334'))
           for i, l in enumerate(get('outro.links', []) or []) if l.get('qr')]
    for fn, url, fg in qrs:
        q = qrcode.QRCode(border=0, box_size=16, error_correction=qrcode.constants.ERROR_CORRECT_M)
        q.add_data(url); q.make(fit=True)
        img = q.make_image(fill_color=fg, back_color='white').convert('RGBA')
        px = np.asarray(img).copy(); px[(px[..., :3] > 200).all(axis=2), 3] = 0
        Image.fromarray(px).save(ROOT / 'assets/brand' / fn)
    import json
    (ROOT / 'assets/art/manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: (v['ink'], v['size']) for k, v in manifest.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
