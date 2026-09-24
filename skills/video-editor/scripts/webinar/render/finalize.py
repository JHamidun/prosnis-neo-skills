"""S11 final assembly (main path): encoded chunks (render/enc, identical NVENC params, IDR at every chunk start) ->
concat -c copy + final/program_mix.wav -> AAC 192k 48 kHz, faststart, title/author metadata.

Refuses to run unless every encoded chunk matches its CURRENT render (size+mtime sidecar of encode_chunks.py) and
its frame count, the mix duration equals the EDL duration (+-0.05 s) and the result has exactly total_frames frames.
A lock file keeps two agents from muxing into the same folder at once.

job.json: "title", "author" (metadata), "final.name" (output file name), audio mix = final/program_mix.wav
usage: python finalize.py --job job.json [--check-only] [--wav <name in final/>] [--out <file name>]
Fallback without per-chunk encodes: assemble.py (one NVENC pass over the concatenated renders).
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
ENC = REN / 'enc'
FIN.mkdir(parents=True, exist_ok=True)
IDX = json.load(open(J.p('edl/chunks/index.json'), encoding='utf-8'))
FPS = J.fps
OUT = FIN / (sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else J.get('final.name', 'program.mp4'))
WAV = FIN / (sys.argv[sys.argv.index('--wav') + 1] if '--wav' in sys.argv else 'program_mix.wav')


def frames(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries', 'stream=nb_read_packets',
                        '-of', 'csv=p=0', str(p)], capture_output=True, text=True)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return -1


def check():
    bad = []
    for c in IDX['chunks']:
        name = c['id'].replace('full_', 'chunk_')
        src, enc, side = REN / f'{name}.mp4', ENC / f'{name}.mp4', ENC / f'{name}.src.json'
        if not src.exists() or not enc.exists() or not side.exists():
            bad.append((name, 'missing src/enc/sidecar'))
            continue
        sig = {'size': src.stat().st_size, 'mtime': src.stat().st_mtime}
        if json.loads(side.read_text()) != sig:
            bad.append((name, 'enc stale vs render'))
            continue
        n = frames(enc)
        if n != c['frames']:
            bad.append((name, f'{n}/{c["frames"]} frames'))
    return bad


def main():
    bad = check()
    print('chunk check:', 'OK' if not bad else bad, flush=True)
    if bad or '--check-only' in sys.argv:
        sys.exit(1 if bad else 0)
    lock = FIN / 'finalize.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f'pid {os.getpid()} {time.strftime("%H:%M:%S")}\n'.encode())
        os.close(fd)
    except FileExistsError:
        sys.exit('finalize.lock exists: another finalize is running (delete the lock if stale)')
    try:
        dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(WAV)],
                                   capture_output=True, text=True).stdout.strip())
        if abs(dur - IDX['total_frames'] / FPS) >= 0.05:
            sys.exit(f'mix duration {dur} != EDL {IDX["total_frames"] / FPS}')
        lst = FIN / 'concat_enc.txt'
        lst.write_text(''.join(f"file '{(ENC / (c['id'].replace('full_', 'chunk_') + '.mp4')).as_posix()}'\n" for c in IDX['chunks']),
                       encoding='utf-8', newline='\n')
        tmp = OUT.with_suffix('.part.mp4')
        meta = []
        if J.get('title'):
            meta += ['-metadata', f"title={J.get('title')}"]
        if J.get('author'):
            meta += ['-metadata', f"artist={J.get('author')}"]
        lang = J.get('final.audio_language', 'rus')
        cmd = ['ffmpeg', '-hide_banner', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst), '-i', str(WAV),
               '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
               *meta, '-metadata:s:a:0', f'language={lang}', '-movflags', '+faststart', str(tmp)]
        t = time.time()
        with open(FIN / 'finalize.log', 'w', encoding='utf-8') as log:
            p = subprocess.run(cmd, stderr=log, **low_flags())
        if p.returncode:
            sys.exit('mux failed, see finalize.log')
        n = frames(tmp)
        if n != IDX['total_frames']:
            sys.exit(f'final frame count {n} != {IDX["total_frames"]}')
        tmp.replace(OUT)
        print('OK', OUT, f'{time.time() - t:.0f} s', f'{OUT.stat().st_size / 1e9:.2f} GB', flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
