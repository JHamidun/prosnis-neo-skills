"""S11 input: 4K sources -> render clips in remotion/public/full/clips (skip-if-done, resumable per file).

Every clip: GPU decode with crop + resize INSIDE the decoder (h264_cuvid -crop t x b x l x r -resize WxH), the colour
matrix BT.601 -> BT.709 converted exactly ONCE on the CPU (colorspace_cuda only changes the range, G-F6), NVENC
p5 VBR cq, GOP 25 without B-frames (Remotion seeks cheaply), bt709 tags, faststart. All ffmpeg at BELOW_NORMAL,
4 in parallel (NVENC takes several sessions). Measured on RTX 4090 Laptop: 4K -> 1600x900 at 90 fps, a camera
tile 115 fps.

Typical clip set of a Zoom recording (job.json "ingest.clips"):
  <part>_main  share area x 0..3440 of 3840 (the right strip with participant names is cut, G-V5), full height,
               2560x1608 (content px = 4K px * 0.744186; the room above 1440 is headroom for punch-ins)
  <part>_cam   host camera tile -> 640x360 + light unsharp
  <part>_cam2  co-host tile, only the range where it is live (ss/dur)
Deck demo videos are copied to remotion/public/full/video/ (job.json deck.videos[].video and/or deck.assets_map).

job.json:
  "ingest": {"src_size": [3840, 2160], "workers": 4,
             "clips": {"p1_main": {"src": "part1", "crop_4k": [0, 0, 3440, 2160], "size": "2560x1608", "cq": 18},
                       "p1_cam":  {"src": "part1", "crop_4k": [3474, 0, 356, 200], "size": "640x360", "sharpen": true, "cq": 17},
                       "p1_cam2": {"src": "part1", "crop_tblr": [224, 1736, 3474, 10], "size": "640x360", "sharpen": true,
                                   "cq": 17, "ss": 1700.0, "dur": null}}}
  crop_4k = [x, y, w, h] in source px (converted to top/bottom/left/right), or crop_tblr given directly.
usage: python ingest.py --job job.json [--test]      (--test: 3 s of every clip into edl/ingest_test/)
"""
import json
import shutil
import subprocess
import sys
import time
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load, low_flags  # noqa: E402

J = load()
PUB = Path(J.p('remotion/public/full'))
TEST = '--test' in sys.argv
OUT = Path(J.p('edl/ingest_test')) if TEST else (PUB / 'clips')
OUT.mkdir(parents=True, exist_ok=True)
LOG = Path(J.p('edl/ingest.log'))
CONV = 'scale=in_color_matrix=bt601:out_color_matrix=bt709:in_range=tv:out_range=tv'
TAGS = ['-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709']
ING = J.get('ingest', {}) or {}
SW, SH = ING.get('src_size', [3840, 2160])
JOBS = ING.get('clips', {})


def log(*a):
    line = time.strftime('%H:%M:%S ') + ' '.join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8', newline='\n') as fh:
        fh.write(line + '\n')


def probe_dur(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def tblr(spec):
    if spec.get('crop_tblr'):
        return tuple(spec['crop_tblr'])
    x, y, w, h = spec.get('crop_4k', [0, 0, SW, SH])
    return (y, SH - y - h, x, SW - x - w)


def run(name):
    spec = JOBS[name]
    src = J.src(spec['src'])
    t, b, l, r = tblr(spec)
    ss, dur = spec.get('ss'), spec.get('dur')
    out = OUT / f'{name}.mp4'
    if TEST:
        ss, dur = (ss or 0.0) + 100.0, 3.0
    want = dur if dur else (probe_dur(src) - (ss or 0.0))
    if out.exists() and probe_dur(out) > want - 1.0:
        log('skip', name)
        return name, 'skip'
    tmp = out.with_name(out.stem + '.part.mp4')
    extra = ',unsharp=5:5:0.35' if spec.get('sharpen') else ''
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-c:v', 'h264_cuvid', '-crop', f'{t}x{b}x{l}x{r}', '-resize', spec['size']]
    if ss:
        cmd += ['-ss', f'{ss:.3f}']
    cmd += ['-i', src]
    if dur:
        cmd += ['-t', f'{dur:.3f}']
    cmd += ['-an', '-vf', CONV + extra + ',format=yuv420p', '-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', str(spec.get('cq', 18)),
            '-b:v', '0', '-g', '25', '-bf', '0', *TAGS, '-movflags', '+faststart', str(tmp)]
    t0 = time.time()
    log('start', name, f'crop {t}x{b}x{l}x{r} -> {spec["size"]}')
    rc = subprocess.Popen(cmd, **low_flags()).wait()
    if rc != 0:
        log('FAIL', name, rc)
        return name, f'fail {rc}'
    tmp.replace(out)
    log('done', name, f'{time.time() - t0:.0f}s', f'{probe_dur(out):.2f}s', f'{out.stat().st_size / 1e6:.0f}MB')
    return name, 'ok'


def copy_videos():
    """clean deck videos: deck.videos[].video (the sync list) + every video insert of a manus-slides assets_map.json"""
    d = PUB / 'video'
    d.mkdir(parents=True, exist_ok=True)
    paths = [J.rel(v['video']) for v in (J.get('deck.videos') or []) if v.get('video')]
    if J.get('deck.assets_map'):
        a = json.load(open(J.rel(J.get('deck.assets_map')), encoding='utf-8'))
        for sid, v in a['slides'].items():
            for ins in v.get('inserts', []):
                if ins.get('type') == 'video' and ins.get('path'):
                    paths.append(ins['path'])
    for p in paths:
        if Path(p).exists():
            dst = d / Path(p).name
            if not dst.exists():
                shutil.copy2(p, dst)
                log('copied', dst.name)


if __name__ == '__main__':
    if not JOBS:
        raise SystemExit('job.json "ingest.clips" is empty (see the docstring)')
    if not TEST:
        copy_videos()
    with ThreadPoolExecutor(max_workers=int(ING.get('workers', 4))) as ex:  # long main clips first, cams alongside
        res = list(ex.map(run, list(JOBS)))
    log('INGEST_DONE', res)
