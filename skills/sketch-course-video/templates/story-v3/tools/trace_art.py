"""Trace unchanged raster sketches into pencil stroke paths (approved v14 method, as in the 23.09 story).

    python trace_art.py <png> <paper|dark> <out.json>

Output Sheet JSON for SketchArt.tsx: {source, sourceWidth, sourceHeight, sourceSha256, arts: {main: {...}}}.
The PNG is referenced by its basename; copy it next to the JSON into the Remotion public folder.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import cv2
import numpy as np

import os  # noqa: E402
SKILL_TRACE = Path(os.environ.get('SKETCH_COURSE_VIDEO_DIR') or Path.home() / '.claude/skills/sketch-course-video') / 'scripts/trace.py'
spec = importlib.util.spec_from_file_location('approved_trace', SKILL_TRACE)
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


def clean(mask, minimum=6):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    keep = np.zeros(count, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= minimum
    return keep[labels]


def silhouette(mask):
    grown = cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(grown, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for contour in contours:
        if cv2.contourArea(contour) < 3:
            continue
        pts = cv2.approxPolyDP(contour, .5, True).reshape(-1, 2)
        out.append('M' + ' L'.join(f'{a},{b}' for a, b in pts) + ' Z')
    return ' '.join(out)


def main():
    src, theme, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    raw = cv2.imread(str(src), cv2.IMREAD_COLOR)
    colors = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB).astype(float)
    h, w = raw.shape[:2]
    r, g, b = colors[:, :, 0], colors[:, :, 1], colors[:, :, 2]
    coral = (r > 155) & (r - g > 28) & (r - b > 48)
    chroma = colors.max(axis=2) - colors.min(axis=2)
    if theme == 'dark':
        ink = (colors.min(axis=2) > 142) & (chroma < 65)
    else:
        ink = (colors.mean(axis=2) < 145) & (chroma < 70)
    ink = clean(ink & ~coral)
    coral = clean(coral)
    outlines = trace.trace_paths(ink, 0, 0)
    outlines.sort(key=lambda p: -p['length'])
    outlines = trace.order_strokes(outlines[:650])
    fills = trace.color_paths(coral, 0, 0)
    if len(fills) > 150:
        fills = sorted(fills, key=lambda p: -p['length'])[:150]
        fills.sort(key=lambda p: p['points'][0][0] + p['points'][0][1])
    paths = []
    for group, portion, offset, is_color in [(outlines, .74, 0, False), (fills, .24, .76, True)]:
        total = sum(max(p['length'], 12) for p in group) or 1
        cursor = offset
        for p in group:
            d = portion * max(p['length'], 12) / total
            paths.append({'points': p['points'], 'width': p['width'], 'start': round(cursor, 6),
                          'duration': round(d, 6), 'color': is_color})
            cursor += d
    sheet = {'source': src.name, 'sourceWidth': w, 'sourceHeight': h,
             'sourceSha256': hashlib.sha256(src.read_bytes()).hexdigest(),
             'arts': {'main': {'crop': [0, 0, w, h], 'paths': paths, 'finish': silhouette(ink | coral)}}}
    out.write_text(json.dumps(sheet, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'png': src.name, 'paths': len(paths), 'ink': len(outlines), 'coral': len(fills),
                      'inkPx': int(ink.sum()), 'coralPx': int(coral.sum())}), flush=True)


if __name__ == '__main__':
    main()
