"""S13: frame-accurate contact sheet - every Nth frame of a span laid out in a grid with frame numbers.

The external check for claims of a model or a viewer: "hard cut at 01:12" (G-Q1), "the pen pops", "the sketch shows an
empty canvas", "the card flashes navy" (G-S5). An eased morph is visible as a smooth series of cells, a cut as a jump
between two neighbours. Default: every 3rd frame, 6 columns, cells 320 px wide.

usage: python contact_sheet.py --job job.json <video.mp4> <from_s> <to_s> [--every 3] [--cols 6] [--w 320] [--out file.jpg]
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load, low_flags  # noqa: E402

J = load()


def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def main():
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and not sys.argv[i - 1].startswith('--')]
    if len(pos) < 3:
        raise SystemExit(__doc__)
    video, t0, t1 = pos[0], float(pos[1]), float(pos[2])
    every, cols, w = arg('--every', 3), arg('--cols', 6), arg('--w', 320)
    fps = J.fps
    W, H = J.get('canvas', [1920, 1080])
    h = round(w * H / W)
    vf = f"select='not(mod(n\\,{every}))',scale={w}:{h}"
    raw = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', f'{t0:.3f}', '-t', f'{t1 - t0:.3f}', '-i', video,
                          '-vf', vf, '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, **low_flags()).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w, 3)
    if not len(frames):
        raise SystemExit('no frames decoded')
    rows = (len(frames) + cols - 1) // cols
    pad = 22
    sheet = Image.new('RGB', (cols * w, rows * (h + pad)), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    f0 = round(t0 * fps)
    for i, fr in enumerate(frames):
        x, y = (i % cols) * w, (i // cols) * (h + pad)
        sheet.paste(Image.fromarray(fr), (x, y + pad))
        n = f0 + i * every
        draw.text((x + 4, y + 4), f'f{n}  {n // fps // 60:02d}:{n / fps % 60:05.2f}', fill=(255, 210, 60), font=font)
    out = Path(arg('--out', str(Path(video).with_name(f'{Path(video).stem}_sheet_{t0:.1f}-{t1:.1f}.jpg'))))
    sheet.save(out, quality=88)
    print('OK', out, len(frames), 'frames', sheet.size)


if __name__ == '__main__':
    main()
