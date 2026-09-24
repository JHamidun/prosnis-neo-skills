"""S11 final assembly, single-pass fallback (no per-chunk encodes): check every Remotion chunk against
edl/chunks/index.json (frame count, 1920x1080, fps), concat demuxer, mux final/program_mix.wav, ONE NVENC encode:
H.264 High, p7 hq, VBR 7 Mbps (max 11), multipass fullres, spatial+temporal AQ, GOP 50, bf 3, bt709 tv,
AAC 192k 48 kHz, -frames:v = EDL total, faststart.
The main path is encode_chunks.py (pipelined while rendering) + finalize.py (concat -c copy): same parameters, done
minutes after the last chunk instead of one long encode at the end.

usage: python assemble.py --job job.json [--check-only]
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
REN, FIN = Path(J.p('render')), Path(J.p('final'))
FIN.mkdir(parents=True, exist_ok=True)
IDX = json.load(open(J.p('edl/chunks/index.json'), encoding='utf-8'))
OUT = FIN / J.get('final.name', 'program.mp4')
FPS = J.fps
W, H = J.get('canvas', [1920, 1080])


def nb_frames(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                        'stream=nb_read_packets,width,height,r_frame_rate', '-of', 'json', str(p)], capture_output=True, text=True)
    s = json.loads(r.stdout)['streams'][0]
    return int(s['nb_read_packets']), s['width'], s['height'], s['r_frame_rate']


def check():
    bad = []
    for c in IDX['chunks']:
        p = REN / (c['id'].replace('full_', 'chunk_') + '.mp4')
        if not p.exists():
            bad.append((p.name, 'missing'))
            continue
        n, w, h, r = nb_frames(p)
        if n != c['frames'] or (w, h, r) != (W, H, f'{FPS}/1'):
            bad.append((p.name, f'{n}/{c["frames"]} frames {w}x{h} {r}'))
    return bad


def main():
    bad = check()
    print('chunk check:', 'OK' if not bad else bad)
    if bad or '--check-only' in sys.argv:
        sys.exit(1 if bad else 0)
    lst = FIN / 'concat.txt'
    lst.write_text(''.join(f"file '{(REN / (c['id'].replace('full_', 'chunk_') + '.mp4')).as_posix()}'\n" for c in IDX['chunks']),
                   encoding='utf-8', newline='\n')
    wav = FIN / 'program_mix.wav'
    if not wav.exists():
        sys.exit('final/program_mix.wav missing (audio/mix_full.py)')
    tmp = OUT.with_suffix('.part.mp4')
    cmd = ['ffmpeg', '-hide_banner', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst), '-i', str(wav),
           '-map', '0:v:0', '-map', '1:a:0',
           '-c:v', 'h264_nvenc', '-preset', 'p7', '-tune', 'hq', '-profile:v', 'high', '-rc', 'vbr', '-multipass', 'fullres',
           '-b:v', '7M', '-maxrate', '11M', '-bufsize', '14M', '-spatial-aq', '1', '-temporal-aq', '1', '-rc-lookahead', '32',
           '-g', '50', '-bf', '3', '-pix_fmt', 'yuv420p', '-r', str(FPS),
           '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
           '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
           '-frames:v', str(IDX['total_frames']), '-movflags', '+faststart', str(tmp)]
    t = time.time()
    with open(FIN / 'assemble.log', 'w', encoding='utf-8') as log:  # ffmpeg log to a FILE, never a PIPE (G-F10)
        p = subprocess.run(cmd, stderr=log, **low_flags())
    if p.returncode:
        sys.exit('encode failed, see assemble.log')
    tmp.replace(OUT)
    s = time.time() - t
    print('OK', OUT, f'{s:.0f} s = {IDX["total_frames"] / s:.1f} fps')


if __name__ == '__main__':
    main()
