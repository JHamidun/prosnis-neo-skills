"""Replace one PDF page's content with an image (e.g. a real screenshot of a live app shown during the talk - the
raffle results in the reference deck): the image is cropped by fractions, the page is filled with the background colour
sampled from the crop, the image is centred and fitted. Other pages are untouched.

usage: python pdf_page_image.py <in.pdf> <out.pdf> <page> <image.png> [--crop x0,y0,x1,y1] [--bg-at x,y]
  --crop  fractions of the image to keep (default 0,0,1,1); the reference cut the half logo row on top and the service
          buttons at the bottom: --crop 0,0.094,1,0.893
  --bg-at pixel of the CROPPED image whose colour fills the page (default: 8 px from the left edge, vertical middle)
"""
import sys
from pathlib import Path

import fitz
from PIL import Image


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and not sys.argv[i - 1].startswith('--')]
    if len(pos) != 4:
        raise SystemExit(__doc__)
    src, out, pno, shot = Path(pos[0]), Path(pos[1]), int(pos[2]), Path(pos[3])
    im = Image.open(shot).convert('RGB')
    W, H = im.size
    x0, y0, x1, y1 = [float(v) for v in (arg('--crop') or '0,0,1,1').split(',')]
    crop = im.crop((int(W * x0), int(H * y0), int(W * x1), int(H * y1)))
    bx, by = [int(v) for v in arg('--bg-at').split(',')] if arg('--bg-at') else (8, crop.height // 2)
    bg = crop.getpixel((bx, by))
    crop_path = out.with_name(out.stem + f'_p{pno}_crop.png')
    crop.save(crop_path, optimize=True)
    doc = fitz.open(src)
    page = doc[pno - 1]
    pw, ph = page.rect.width, page.rect.height
    sh = page.new_shape()
    sh.draw_rect(page.rect)
    sh.finish(color=None, fill=tuple(c / 255 for c in bg), fill_opacity=1)
    sh.commit()
    cw, ch = crop.size
    scale = min(pw / cw, ph / ch)
    iw, ih = cw * scale, ch * scale
    rect = fitz.Rect((pw - iw) / 2, (ph - ih) / 2, (pw + iw) / 2, (ph + ih) / 2)
    page.insert_image(rect, filename=str(crop_path))
    doc.save(out, garbage=3, deflate=True)
    print('crop', crop.size, 'bg', bg, 'rect', [round(v) for v in rect], 'saved', out, out.stat().st_size)


if __name__ == '__main__':
    main()
