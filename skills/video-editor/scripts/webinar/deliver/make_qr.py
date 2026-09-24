"""QR codes for the outro / covers / PDFs from URLs - and the check that they decode back to exactly that URL.

A QR is only "done" when a decoder reads it: the reference run found a cover template whose default QR pointed at a
404 profile. Colours: dark modules on transparent (for dark stages pass --fg '#FFFFFF').

job.json outro.links[] {"label", "url", "qr": true, "qr_file": "qr-bot.png"} -> remotion/public_lite/brand/<qr_file>
usage: python make_qr.py --job job.json [--fg '#010334'] [--out-dir <dir>]
       python make_qr.py <url> <out.png> [--fg '#010334']          (single code, no job)
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import qrcode
from PIL import Image


def make(url, out, fg='#010334', box=16):
    q = qrcode.QRCode(border=2, box_size=box, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    img = q.make_image(fill_color=fg, back_color='white').convert('RGBA')
    px = np.asarray(img).copy()
    white = (px[..., :3] > 200).all(axis=2)
    check = cv2.cvtColor(np.where(white[..., None], 255, 0).astype(np.uint8).repeat(3, axis=2), cv2.COLOR_RGB2BGR)
    got, _, _ = cv2.QRCodeDetector().detectAndDecode(check)
    if got != url:
        raise SystemExit(f'QR check failed for {out}: decoded {got!r} != {url!r}')
    px[white, 3] = 0
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(px).save(out)
    print('OK', out, img.size, url)


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    fg = arg('--fg', '#010334')
    if '--job' in sys.argv or os.environ.get('WEBINAR_JOB'):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
        from job import load
        J = load()
        out_dir = Path(arg('--out-dir', J.p('remotion/public_lite/brand')))
        links = [l for l in (J.get('outro.links', []) or []) if l.get('qr')]
        if not links:
            raise SystemExit('job.json outro.links has no {"qr": true} entries')
        for i, l in enumerate(links):
            make(l['url'], out_dir / (l.get('qr_file') or f'qr-{i}.png'), fg)
        return
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and not sys.argv[i - 1].startswith('--')]
    if len(pos) != 2:
        raise SystemExit(__doc__)
    make(pos[0], pos[1], fg)


if __name__ == '__main__':
    main()
