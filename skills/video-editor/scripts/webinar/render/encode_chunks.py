"""S11 output, pipelined: every finished Remotion chunk -> NVENC chunk with IDENTICAL parameters, while the workers
keep rendering the rest. The final file is then concat -c copy + audio mux (finalize.py), minutes instead of an hour.

render/chunk_NNN.mp4 (x264 crf16 mezzanine) -> render/enc/chunk_NNN.mp4
H.264 High 1920x1080, NVENC p7 hq VBR 7M (max 11M), multipass fullres, spatial+temporal AQ, GOP 50, bf 3, bt709 tv,
video only. NVDEC decode -> CUDA frames -> NVENC: GPU only, the CPU stays with the Remotion workers.
Every chunk starts with an IDR and all chunks share SPS/PPS, so concat -c copy is seamless (checked: 15000 frames,
continuous pts, IDR at the seam, clean decode).
A sidecar <chunk>.src.json (size + mtime of the render) makes stale encodes visible: a render withdrawn or replaced
after an EDL fix is re-encoded automatically, the old encode goes to enc/stale/.
Skip-if-done, .part + rename = resumable. Polls every 20 s until all chunks are encoded.

job.json "render.encode" overrides: {"b": "7M", "maxrate": "11M", "bufsize": "14M", "preset": "p7", "gop": 50}
usage: python encode_chunks.py --job job.json [--once]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load, low_flags  # noqa: E402

J = load()
REN = Path(J.p('render'))
ENC = REN / 'enc'
ENC.mkdir(parents=True, exist_ok=True)
IDX = json.load(open(J.p('edl/chunks/index.json'), encoding='utf-8'))
LOG = ENC / 'encode_log.jsonl'
FPS = J.fps
W, H = J.get('canvas', [1920, 1080])
EC = J.get('render.encode', {}) or {}


def vparams():
    return ['-c:v', 'h264_nvenc', '-preset', EC.get('preset', 'p7'), '-tune', 'hq', '-profile:v', 'high', '-rc', 'vbr', '-multipass', 'fullres',
            '-b:v', EC.get('b', '7M'), '-maxrate', EC.get('maxrate', '11M'), '-bufsize', EC.get('bufsize', '14M'), '-spatial-aq', '1',
            '-temporal-aq', '1', '-rc-lookahead', '32', '-g', str(EC.get('gop', 50)), '-bf', '3', '-r', str(FPS),
            '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv']


def frames(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                        'stream=nb_read_packets,width,height,r_frame_rate', '-of', 'json', str(p)], capture_output=True, text=True)
    try:
        s = json.loads(r.stdout)['streams'][0]
        return int(s['nb_read_packets']), (s['width'], s['height'], s['r_frame_rate'])
    except Exception:  # noqa: BLE001
        return -1, None


def encode(c):
    name = c['id'].replace('full_', 'chunk_')
    src, out = REN / f'{name}.mp4', ENC / f'{name}.mp4'
    side = ENC / f'{name}.src.json'
    geo_ok = (W, H, f'{FPS}/1')
    if not src.exists():
        if out.exists():  # source withdrawn for a re-render -> encode is stale
            (ENC / 'stale').mkdir(exist_ok=True)
            out.replace(ENC / 'stale' / f'{name}.{int(time.time())}.mp4')
            side.unlink(missing_ok=True)
        return 'wait'
    sig = {'size': src.stat().st_size, 'mtime': src.stat().st_mtime}
    if out.exists():
        try:
            if json.loads(side.read_text()) == sig:
                return 'done'
        except Exception:  # noqa: BLE001
            pass
        (ENC / 'stale').mkdir(exist_ok=True)  # source replaced -> re-encode
        out.replace(ENC / 'stale' / f'{name}.{int(time.time())}.mp4')
    if time.time() - sig['mtime'] < 5:
        return 'wait'
    n, geo = frames(src)
    if n != c['frames'] or geo != geo_ok:
        return f'bad src {n}/{c["frames"]} {geo}'
    tmp = ENC / f'{name}.part.mp4'
    cmd = ['ffmpeg', '-hide_banner', '-nostats', '-y', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-i', str(src),
           '-map', '0:v:0', *vparams(), '-frames:v', str(c['frames']), '-an', str(tmp)]
    t = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', **low_flags())
    if p.returncode:
        (ENC / f'{name}.err.txt').write_text(p.stderr[-6000:], encoding='utf-8')
        return 'encode failed'
    n2, geo2 = frames(tmp)
    if n2 != c['frames'] or geo2 != geo_ok:
        return f'bad out {n2} {geo2}'
    tmp.replace(out)
    side.write_text(json.dumps(sig))
    s = time.time() - t
    with open(LOG, 'a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps({'id': name, 'frames': n2, 'seconds': round(s, 1), 'fps': round(n2 / s, 1),
                            'mb': round(out.stat().st_size / 1e6, 1), 'at': time.strftime('%H:%M:%S')}) + '\n')
    return f'encoded {s:.0f}s {n2 / s:.0f} fps'


def main():
    while True:
        states = {}
        for c in IDX['chunks']:
            r = encode(c)
            states[c['id']] = r
            if r.startswith('encoded') or r.startswith('bad') or r.startswith('encode failed'):
                print(time.strftime('%H:%M:%S'), c['id'], r, flush=True)
        done = sum(1 for v in states.values() if v == 'done' or v.startswith('encoded'))
        if done == len(IDX['chunks']):
            print(time.strftime('%H:%M:%S'), 'ALL ENCODED', flush=True)
            return
        if '--once' in sys.argv:
            print(states)
            return
        time.sleep(20)


if __name__ == '__main__':
    main()
