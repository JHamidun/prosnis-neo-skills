"""Bundle / render / stills for the webinar stories project, at BELOW_NORMAL priority (children inherit it).

    python tools/render.py bundle                         # src -> out/bundle (once; ~10 min on a loaded machine)
    python tools/render.py render <clip> [--concurrency 6] # -> out/<clip>.mp4
    python tools/render.py still <clip> <frame> [<frame> ...]  # -> out/proof/<clip>_f<frame>.jpg

Before render/still the clip folder public/clips/<clip> is synced into out/bundle/public/clips/<clip>
(the bundle serves its own copy of public/, so new clips never need a re-bundle).
At most two renders at once (out/.render_slot1|2): the machine also runs the long montage render.
Headless Chrome sometimes misses its start window on a loaded machine, so every call is retried.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ['node', 'node_modules/@remotion/cli/remotion-cli.js']
LOW = getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)


def env():
    e = dict(os.environ)
    tmp = os.environ.get('STORY_TMP') or str(ROOT / 'out/tmp')   # never the system drive (it may be full)
    Path(tmp).mkdir(parents=True, exist_ok=True)
    e['TEMP'] = e['TMP'] = tmp
    return e


def run(args, log, tries=4):
    for a in range(1, tries + 1):
        with open(log, 'w', encoding='utf-8') as fh:
            code = subprocess.call(CLI + args, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, env=env(), creationflags=LOW)
        if code == 0:
            return True
        tail = Path(log).read_text(encoding='utf-8', errors='replace').strip().splitlines()[-3:]
        print(f'retry {a}: exit {code}', *tail, sep='\n  ', flush=True)
    return False


def sync(clip):
    src, dst = ROOT / 'public/clips' / clip, ROOT / 'out/bundle/public/clips' / clip
    if not (ROOT / 'out/bundle/index.html').exists():
        sys.exit('no bundle: run `python tools/render.py bundle` first')
    if not src.exists():
        sys.exit(f'no clip folder {src}')
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns('_*'))


class Slot:
    def __enter__(self):
        while True:
            for s in (1, 2):
                p = ROOT / f'out/.render_slot{s}'
                try:
                    p.mkdir()
                    self.p = p
                    return self
                except FileExistsError:
                    pass
            time.sleep(20)

    def __exit__(self, *exc):
        self.p.rmdir()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['bundle', 'render', 'still'])
    ap.add_argument('clip', nargs='?')
    ap.add_argument('frames', nargs='*', type=int)
    ap.add_argument('--concurrency', type=int, default=6)
    ap.add_argument('--out')
    a = ap.parse_args()
    (ROOT / 'out').mkdir(exist_ok=True)
    if a.cmd == 'bundle':
        ok = run(['bundle', 'src/index.ts', '--out-dir=out/bundle', '--log=error'], ROOT / 'out/bundle.log', tries=2)
        print('BUNDLE_OK' if ok else 'BUNDLE_FAILED', flush=True)
        sys.exit(0 if ok else 1)
    sync(a.clip)
    props = f'--props={{"clip":"{a.clip}"}}'
    if a.cmd == 'render':
        out = a.out or f'out/{a.clip}.mp4'
        with Slot():
            ok = run(['render', 'out/bundle', 'StoryV3', out, props, '--codec=h264', '--crf=18', '--pixel-format=yuv420p',
                      f'--concurrency={a.concurrency}', '--timeout=180000', '--log=error'], ROOT / f'out/render_{a.clip}.log')
        print(f'RENDER_OK {ROOT / out}' if ok else 'RENDER_FAILED', flush=True)
        sys.exit(0 if ok else 1)
    (ROOT / 'out/proof').mkdir(exist_ok=True)
    bad = 0
    for fr in a.frames:
        out = f'out/proof/{a.clip}_f{fr}.jpg'
        ok = run(['still', 'out/bundle', 'StoryV3', out, props, f'--frame={fr}', '--image-format=jpeg', '--timeout=120000', '--log=error'],
                 ROOT / f'out/proof/{a.clip}_f{fr}.log')
        print(('ok ' if ok else 'FAILED ') + out, flush=True)
        bad += not ok
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
