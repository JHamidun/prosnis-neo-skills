"""Cut one story's media from the webinar recordings by its EDL (generalized prep of the 23.09 webinar stories).

    python tools/prep_from_recording.py --job <webinar job.json> <id>      # reads public/clips/<id>/edl.json

The webinar job (skill video-editor, templates/job.example.json) gives the sources (sources[].tag = P1, P2 ...), the
words (<job>/transcript/<source id>.words.json) and the "stories" block:
  "stories": {"share": {"P1": [0, 0, 3440, 2160]},            share area per source in 4K px = the frame minus the Zoom
                                                               strip with participant names (never show the strip)
              "faces": {"P1:host": [3560, 22, 180, 180]},      square around the face inside the speaker's Zoom tile
                                                               (vision/scenes.json camera_tiles, checked on 4K frames)
              "speakers": {"host": {"match": "<ASR name prefix>", "short": "<Имя>"},
                           "cohost": {"match": "<prefix>", "short": "<Имя>"}}}
edl.json:
  {"pieces": [{"src": "P1", "in": s, "out": s,                   audio + face time (source seconds)
               "part": "process"|"result",                        default process; result pieces go last
               "screen": {"src": "P1", "in": s} | [{"src", "in", "dur"}, ..., {"src", "in"}],
                                                                  optional B-roll (default: same as audio); a list plays in
                                                                  order, the last item fills the rest of the piece
               "crop": [x, y, w, h],                              optional screen crop in 4K px (also per screen item)
               "face": "host"|"cohost"|null,                      default: majority speaker of the words in the piece
               "note": "..."}],                                   a piece whose "in" equals the previous "out" (same src)
                                                                  is CONTINUOUS audio: no cut, no fade, no face re-framing
   "words_fix": {"привезти": "привести"} | [{"src": "P1", "t": 657.99, "to": "всё,"}, ...]}
                                                                  dict = every token with that core; list = one word by its
                                                                  source start ("to": "" removes a filler)
Writes public/clips/<id>/:
  screen.mp4 (+ result.mp4)        2160x1262 (= panel 1000:584), 30 fps, crop letterboxed with the crop's own edge colour
  face.mp4   (+ result_face.mp4)   440x440 square around the speaker's face, 30 fps
  voice.wav                        all pieces, 12 ms fades at every cut, highpass + gentle comp, loudnorm -16 LUFS / -1.5 dBTP
  words.json                       caption words on the story clock ({w, s, e, sp})
  media.json                       process_dur, result_dur, cuts, the piece map story<->source (place zooms/steps with it)
  sheet_screen.jpg (+ sheet_result.jpg)  screen contact sheet with a 0.1 grid and story timecodes
Temp pieces live in _prep/ keyed by the piece content (an EDL edit never reuses a stale piece). Frame counts are exact:
every piece = round(dur*30) frames. Fonts for the sheet: public/fonts/Manrope-Bold.ttf.
"""
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FPS = 30
W, H = 2160, 1262
AUDIO = 'highpass=f=80,acompressor=threshold=-22dB:ratio=2.5:attack=10:release=200:makeup=2'


def load_job():
    argv = sys.argv
    if '--job' not in argv:
        raise SystemExit(__doc__)
    i = argv.index('--job')
    f = Path(os.path.expanduser(argv[i + 1])).resolve()
    del argv[i:i + 2]
    cfg = json.loads(f.read_text(encoding='utf-8'))
    root = Path(os.path.expanduser(cfg.get('root') or str(f.parent)))
    root = root if root.is_absolute() else (f.parent / root).resolve()
    return cfg, root


CFG, JOBROOT = load_job()
ST = CFG.get('stories', {})
_parts = [s for s in CFG.get('sources', []) if s.get('kind') != 'recorder']
TAG2SRC = {(s.get('tag') or f'P{i}'): s for i, s in enumerate(_parts, 1)}


def rel(p):
    q = Path(os.path.expanduser(str(p)))
    return str(q if q.is_absolute() else JOBROOT / q)


SRC = {tag: rel(s['path']) for tag, s in TAG2SRC.items()}
WORDS = {tag: JOBROOT / f"transcript/{s['id']}.words.json" for tag, s in TAG2SRC.items()}
SHARE = {tag: ST.get('share', {}).get(tag, [0, 0, 3440, 2160]) for tag in TAG2SRC}
FACE = {tuple(k.split(':')): v for k, v in (ST.get('faces') or {}).items()}
SPK = ST.get('speakers') or {'host': {'match': '', 'short': ''}}
DEFAULT = next(iter(SPK))


def ff(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *map(str, args)], check=True)


def edge_colour(src, t, crop):
    x, y, w, h = crop
    b = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', src, '-frames:v', '1', '-vf', f'crop={w}:{h}:{x}:{y}',
                        '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True, check=True).stdout
    im = Image.open(io.BytesIO(b)).convert('RGB')
    cols = [im.crop((0, 0, 12, im.height)), im.crop((im.width - 12, 0, im.width, im.height))]
    px = sorted(tuple(p) for c in cols for p in (c.resize((2, 64)).get_flattened_data() if hasattr(Image.Image, 'get_flattened_data')
                                                 else c.resize((2, 64)).getdata()))
    r, g, bb = px[len(px) // 2]
    return f'0x{r:02X}{g:02X}{bb:02X}'


def who_of(name):
    for person, spec in SPK.items():
        if spec.get('match') and (name or '').startswith(spec['match']):
            return person
    return DEFAULT


_WCACHE = {}


def speaker(src, a, b):
    if src not in _WCACHE:
        _WCACHE[src] = json.load(open(WORDS[src], encoding='utf-8'))['words']
    ws = [w for w in _WCACHE[src] if a - .05 <= w['start'] and w['end'] <= b + .08]
    votes = {}
    for w in ws:
        p = who_of(w.get('speaker', ''))
        votes[p] = votes.get(p, 0) + 1
    other = [p for p, v in votes.items() if p != DEFAULT and v > len(ws) / 2]  # the host unless someone else has > half
    return (other[0] if other else DEFAULT), ws


def sheet(video, out, dur, start=0.0, n=20):
    fnt = ImageFont.truetype(str(ROOT / 'public/fonts/Manrope-Bold.ttf'), 22)
    tiles = []
    for i in range(n):
        t = dur * (i + .5) / n
        b = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', str(video), '-frames:v', '1', '-vf', 'scale=432:252',
                            '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True, check=True).stdout
        im = Image.open(io.BytesIO(b)).convert('RGB')
        d = ImageDraw.Draw(im)
        for k in range(1, 10):
            d.line([(im.width * k / 10, 0), (im.width * k / 10, im.height)], fill=(255, 0, 255), width=1)
            d.line([(0, im.height * k / 10), (im.width, im.height * k / 10)], fill=(255, 0, 255), width=1)
        d.rectangle([0, 0, 96, 28], fill='black')
        d.text((4, 2), f'{start + t:.1f}s', fill='yellow', font=fnt)
        tiles.append(im)
    cols = 4
    s = Image.new('RGB', (cols * 440, (len(tiles) + cols - 1) // cols * 260), 'white')
    for i, im in enumerate(tiles):
        s.paste(im, ((i % cols) * 440, (i // cols) * 260))
    s.save(out, quality=85)


def main():
    cid = sys.argv[1]
    clip = ROOT / 'public/clips' / cid
    edl = json.load(open(clip / 'edl.json', encoding='utf-8'))
    fix = edl.get('words_fix', {})
    tmp = clip / '_prep'
    tmp.mkdir(exist_ok=True)
    pieces = sorted(edl['pieces'], key=lambda p: p.get('part', 'process') == 'result')   # stable: process first
    clock, words, pmap, cuts = 0.0, [], [], []
    lists = {'process': ([], []), 'result': ([], [])}
    wavs = []
    prev = None
    starts = []                                    # (index of the piece's first word, is a hard cut)
    for i, p in enumerate(pieces):
        src, a, b = p['src'], float(p['in']), float(p['out'])
        key = hashlib.md5(json.dumps(p, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]
        n = round((b - a) * FPS)
        d = n / FPS
        who, ws = speaker(src, a, b)
        face = p.get('face', who)
        part = p.get('part', 'process')
        cont_in = bool(prev) and prev['src'] == src and abs(prev['out'] - a) < .02
        nxt = pieces[i + 1] if i + 1 < len(pieces) else None
        cont_out = bool(nxt) and nxt['src'] == src and abs(float(nxt['in']) - b) < .02
        scr = p.get('screen') or {'src': src, 'in': a}
        scr = scr if isinstance(scr, list) else [scr]
        left = n  # screen piece(s), B-roll aware: exact frame counts, the last item takes the remainder
        for k, sc in enumerate(scr):
            m = left if k == len(scr) - 1 else min(left, round(float(sc['dur']) * FPS))
            left -= m
            if m <= 0:
                continue
            crop = sc.get('crop') or p.get('crop') or SHARE[sc['src']]
            sv = tmp / f'{i:02d}_{k}_{key}_screen.mp4'
            if not sv.exists():
                x, y, w, h = crop
                col = edge_colour(SRC[sc['src']], sc['in'] + .2, crop)
                ff('-ss', sc['in'], '-t', m / FPS + .5, '-i', SRC[sc['src']], '-vf',
                   f'crop={w}:{h}:{x}:{y},scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,'
                   f'pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={col},fps={FPS},setsar=1,tpad=stop_mode=clone:stop_duration=1',
                   '-frames:v', m, '-an', '-c:v', 'libx264', '-crf', 17, '-preset', 'medium', '-pix_fmt', 'yuv420p', sv)
            lists[part][0].append(sv)
        sc, crop = scr[0], scr[0].get('crop') or p.get('crop') or SHARE[scr[0]['src']]
        if face:  # face piece (always synced to the audio)
            fv = tmp / f'{i:02d}_{key}_face.mp4'
            if not fv.exists():
                if (src, face) not in FACE:
                    raise SystemExit(f'stories.faces has no "{src}:{face}" square')
                x, y, w, h = FACE[(src, face)]
                ff('-ss', a, '-t', d + .5, '-i', SRC[src], '-vf',
                   f'crop={w}:{h}:{x}:{y},scale=440:440:flags=lanczos,fps={FPS},setsar=1,tpad=stop_mode=clone:stop_duration=1',
                   '-frames:v', n, '-an', '-c:v', 'libx264', '-crf', 17, '-preset', 'medium', '-pix_fmt', 'yuv420p', fv)
            lists[part][1].append(fv)
        aw = tmp / f'{i:02d}_{key}_{int(cont_in)}{int(cont_out)}.wav'  # a 1 s wider window settles the compressor, then trim
        if not aw.exists():
            pre = min(1.0, a)
            fades = ('' if cont_in else ',afade=t=in:d=0.012') + ('' if cont_out else f',afade=t=out:st={d - .012:.4f}:d=0.012')
            ff('-ss', a - pre, '-t', d + pre + 1, '-i', SRC[src], '-vn', '-af',
               f'aresample=48000,{AUDIO},atrim=start={pre}:duration={d},asetpts=N/SR/TB{fades},apad=whole_dur={d}',
               '-ac', 2, '-ar', 48000, '-c:a', 'pcm_s16le', aw)
        wavs.append(aw)
        starts.append((len(words), not cont_in))
        for w in ws:
            inside = min(w['end'], b) - max(w['start'], a)
            if inside < .5 * max(w['end'] - w['start'], .01):          # a boundary word belongs to the piece holding most of it
                continue
            t = w['punctuated_word']
            core = t.strip('.,!?…:;«»"')
            if isinstance(fix, dict) and core in fix:
                t = t.replace(core, fix[core])
            for fx in (fix if isinstance(fix, list) else []):
                if fx.get('src', src) == src and abs(float(fx['t']) - w['start']) < .06:
                    t = fx['to']
            if not t:
                continue
            words.append({'w': t, 's': round(clock + max(0.0, w['start'] - a), 3), 'e': round(clock + min(d, w['end'] - a), 3),
                          'sp': SPK[who_of(w.get('speaker', ''))].get('short', '')})
        pmap.append({'story_in': round(clock, 3), 'story_out': round(clock + d, 3), 'src': src, 'in': a, 'out': round(a + d, 3),
                     'screen': scr, 'crop': crop, 'face': face, 'part': part, 'continuous_from_prev': cont_in, 'note': p.get('note', '')})
        if i and not cont_in:
            cuts.append(round(clock, 3))
        clock += d
        prev = {'src': src, 'out': b}
    # sentence case across hard cuts: «…нейросеть, | А теперь» -> «нейросеть. А теперь», «блин. | один» -> «блин. Один»
    for k, hard in starts:
        if not hard or k == 0 or k >= len(words):
            continue
        pw, nw = words[k - 1], words[k]
        if pw['w'][-1:] in '.?!…' and nw['w'][:1].islower():
            nw['w'] = nw['w'][:1].upper() + nw['w'][1:]
        elif pw['w'].endswith(',') and nw['w'][:1].isupper():
            pw['w'] = pw['w'][:-1] + '.'
    if words and words[-1]['w'].endswith(','):
        words[-1]['w'] = words[-1]['w'][:-1] + '.'
    pdur = sum(x['story_out'] - x['story_in'] for x in pmap if x['part'] == 'process')
    rdur = clock - pdur

    def concat(files, out):
        if not files:
            return
        lst = tmp / (out.stem + '.txt')
        lst.write_text(''.join(f"file '{f.as_posix()}'\n" for f in files), encoding='utf-8', newline='\n')
        ff('-f', 'concat', '-safe', 0, '-i', lst, '-c', 'copy', '-movflags', '+faststart', out)

    concat(lists['process'][0], clip / 'screen.mp4')
    concat(lists['process'][1], clip / 'face.mp4')
    concat(lists['result'][0], clip / 'result.mp4')
    concat(lists['result'][1], clip / 'result_face.mp4')
    inputs = [x for w in wavs for x in ('-i', w)]
    ff(*inputs, '-filter_complex', ''.join(f'[{k}:a]' for k in range(len(wavs))) + f'concat=n={len(wavs)}:v=0:a=1,'
       'loudnorm=I=-16:TP=-1.5:LRA=11[a]', '-map', '[a]', '-ar', 48000, '-ac', 2, '-c:a', 'pcm_s16le', clip / 'voice.wav')
    (clip / 'words.json').write_text(json.dumps(words, ensure_ascii=False), encoding='utf-8', newline='\n')
    media = {'clip': cid, 'fps': FPS, 'process_dur': round(pdur, 3), 'result_dur': round(rdur, 3), 'total_voice': round(clock, 3),
             'cuts': cuts, 'has_face': bool(lists['process'][1]), 'has_result_face': bool(lists['result'][1]),
             'screen_size': [W, H], 'pieces': pmap, 'words': len(words)}
    (clip / 'media.json').write_text(json.dumps(media, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    sheet(clip / 'screen.mp4', clip / 'sheet_screen.jpg', pdur)
    if rdur > 0:
        sheet(clip / 'result.mp4', clip / 'sheet_result.jpg', rdur, start=pdur, n=8)
    print(json.dumps({k: media[k] for k in ('process_dur', 'result_dur', 'cuts', 'words')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
