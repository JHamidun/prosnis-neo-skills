"""Cut the speaker out of the chosen full-resolution frame (rembg, model birefnet-portrait) -> RGBA PNG with clean edges.

Edge decontamination: semi-transparent edge pixels are un-premultiplied against the known colour of the (virtual)
background, then a 2-iteration alpha choke + 1.2 px blur kills the last halo. Leftovers that rembg keeps (a chair
headrest behind a shoulder in the reference run) are removed by a hand polygon on the alpha - check the cutout on a
zoomed edge preview before using it.
Also writes rim_<name>.png (the alpha, used by cover.html for the rim light).

usage: python cutout.py <frame.png> <out name.png> [--box 0.26,0.04,0.82,1.0] [--bg 0.985,0.965,0.925]
  --box = person region (fractions) incl. chair/mic, --bg = background colour 0..1 (cream virtual background by default)
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from rembg import new_session, remove


def arg(name, default):
    return [float(x) for x in sys.argv[sys.argv.index(name) + 1].split(',')] if name in sys.argv else default


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    src, name = sys.argv[1], sys.argv[2]
    im = Image.open(src).convert('RGB')
    W, H = im.size
    bx = arg('--box', [0.26, 0.04, 0.82, 1.0])
    box = (int(bx[0] * W), int(bx[1] * H), int(bx[2] * W), int(bx[3] * H))
    crop = im.crop(box)
    rgba = remove(crop, session=new_session('birefnet-portrait'), post_process_mask=True)
    a = np.asarray(rgba)[..., 3].astype(np.float32) / 255.0
    rgb = np.asarray(crop).astype(np.float32) / 255.0
    bg = np.array(arg('--bg', [0.985, 0.965, 0.925]), np.float32)
    edge = (a > 0.02) & (a < 0.98)
    af = np.clip(a, 0.05, 1.0)[..., None]
    fg = np.clip((rgb - (1 - af) * bg) / af, 0, 1)
    rgb2 = np.where(edge[..., None], fg, rgb)
    a8 = (a * 255).astype(np.uint8)
    a8 = cv2.erode(a8, np.ones((3, 3), np.uint8), iterations=2)
    a8 = cv2.GaussianBlur(a8, (0, 0), 1.2)
    out = np.dstack([(rgb2 * 255).astype(np.uint8), a8])
    ys, xs = np.where(a8 > 10)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    dst = Path(name)
    Image.fromarray(out[y0:y1 + 1, x0:x1 + 1], 'RGBA').save(dst)
    rim = np.dstack([np.full_like(a8, 255)] * 3 + [a8])[y0:y1 + 1, x0:x1 + 1]
    Image.fromarray(rim, 'RGBA').save(dst.with_name('rim_' + dst.name))
    print('bbox in crop', x0, y0, x1, y1, 'size', x1 - x0 + 1, y1 - y0 + 1, 'crop', crop.size)


if __name__ == '__main__':
    main()
