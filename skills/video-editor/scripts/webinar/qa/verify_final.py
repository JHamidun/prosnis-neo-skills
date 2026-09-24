"""S13: technical QA of the final programme (or of one encoded chunk with --chunk NNN) - external measurements only.

1. streams: H.264 1920x1080 at the job fps, packet count == EDL frames, AAC 48 kHz stereo, durations, bitrate;
2. loudness: EBU R128 integrated / true peak / LRA of the final audio (target -16 LUFS / -1.5 dBTP);
3. black frames (NVDEC -> scale_cuda -> blackdetect) and long silences, listed with timestamps;
4. A/V sync at N random points of the studio plan vs the SOURCE recordings:
   - audio: final audio at T vs the source audio at S (audio_plan voice piece) -> xcorr offset (ms);
   - video: motion energy of the host camera window in the final (tokens layout.studio.cam) vs the camera tile of the
     4K source at S -> xcorr lag (frames). Both ~0 => picture and sound sit where the source had them.
   This is the check that found the camera 91 f (3.64 s) ahead of the voice after every chapter card (G-E6):
   lag +96 f, corr 0.55-0.82 on the broken chunks, lag 0 (corr 0.54-0.998) on the good ones.

Camera tiles in the 4K source: job.json ingest.clips (crop_4k / crop_tblr of the clip the EDL cam uses).
usage: python verify_final.py --job job.json [--video final.mp4 | --chunk NNN] [--points 5] [--report out.json]
"""
import bisect
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
FPS = J.fps
E = json.load(open(J.p('edl/edl.json'), encoding='utf-8'))
A = json.load(open(J.p('edl/audio_plan.json'), encoding='utf-8'))
T = json.load(open(J.p('style/tokens.json'), encoding='utf-8'))
CFG = J.data('edl/edl_config.json', {})
ING = J.get('ingest', {}) or {}
SW, SH = ING.get('src_size', [3840, 2160])


def cam_tiles():
    """{EDL cam clip path: (src id, [x, y, w, h] in the 4K source)} from job.json ingest.clips"""
    out = {}
    for name, spec in (ING.get('clips') or {}).items():
        if spec.get('crop_tblr'):
            t, b, l, r = spec['crop_tblr']
            rect = [l, t, SW - l - r, SH - t - b]
        else:
            rect = spec.get('crop_4k')
        out[f'full/clips/{name}.mp4'] = (spec['src'], rect, spec.get('ss') or 0.0)
    return out


TILES = cam_tiles()
CAMS = {f: src for src, f in (CFG.get('clips', {}).get('cam') or {}).items()}

args = sys.argv[1:]
chunk = args[args.index('--chunk') + 1] if '--chunk' in args else None
npts = int(args[args.index('--points') + 1]) if '--points' in args else 5
if chunk:
    idx = json.load(open(J.p('edl/chunks/index.json'), encoding='utf-8'))
    c = next(c for c in idx['chunks'] if c['id'] == f'full_{chunk}')
    VIDEO, F0, F1 = Path(J.p(f'render/enc/chunk_{chunk}.mp4')), c['from'], c['to']
else:
    VIDEO = Path(args[args.index('--video') + 1]) if '--video' in args else Path(J.p('final')) / J.get('final.name', 'program.mp4')
    F0, F1 = 0, E['durationInFrames']


def run(cmd, binary=False):
    p = subprocess.run(cmd, capture_output=True)
    return p.stdout if binary else (p.stdout.decode('utf-8', 'replace'), p.stderr.decode('utf-8', 'replace'))


def probe():
    out, _ = run(['ffprobe', '-v', 'error', '-count_packets', '-show_entries',
                  'stream=codec_type,codec_name,profile,width,height,r_frame_rate,pix_fmt,nb_read_packets,sample_rate,channels,duration,bit_rate:format=duration,size,bit_rate',
                  '-of', 'json', str(VIDEO)])
    return json.loads(out)


def loudness():
    _, err = run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(VIDEO), '-vn', '-af', 'ebur128=peak=true:framelog=quiet', '-f', 'null', '-'])
    i = re.findall(r'I:\s+(-?[\d.]+) LUFS', err)
    tp = re.findall(r'Peak:\s+(-?[\d.]+) dBFS', err)
    lra = re.findall(r'LRA:\s+(-?[\d.]+) LU', err)
    return {'integrated_lufs': float(i[-1]) if i else None, 'true_peak_dbtp': float(tp[-1]) if tp else None, 'lra': float(lra[-1]) if lra else None}


def black_and_silence(has_audio):
    cmd = ['ffmpeg', '-hide_banner', '-nostats', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-i', str(VIDEO),
           '-vf', 'scale_cuda=320:180,hwdownload,format=nv12,blackdetect=d=0.2:pix_th=0.06:pic_th=0.97']
    if has_audio:
        cmd += ['-af', 'silencedetect=n=-45dB:d=2.5']
    cmd += ['-f', 'null', '-']
    _, err = run(cmd)
    blacks = [(float(a), float(b)) for a, b in re.findall(r'black_start:([\d.]+) black_end:([\d.]+)', err)]
    sil_s = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', err)]
    sil_e = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', err)]
    return blacks, list(zip(sil_s, sil_e + [None] * (len(sil_s) - len(sil_e))))


def layout_at(f):
    L = E['layouts']
    i = bisect.bisect_right([x['frame'] for x in L], f) - 1
    cur = L[i]
    nxt = L[i + 1]['frame'] if i + 1 < len(L) else 10 ** 9
    return cur['layout'], f - cur['frame'], nxt - f


def cam_at(f):
    for c in E['cams']:
        if c['from'] <= f < c['to']:
            return c
    return None


def voice_at(t):
    for v in A['voice']:
        if v['at_s'] <= t < v['at_s'] + (v['t1'] - v['t0']):
            return v
    return None


def candidates():
    out = []
    for f in range(F0 + 200, F1 - 200, FPS):
        lay, since, until = layout_at(f)
        if lay != 'studio' or since < 60 or until < 160:
            continue
        c = cam_at(f)
        if not c or f - c['from'] < 120 or c['to'] - f < 120 or c['src'] not in TILES:
            continue
        t = f / FPS
        v = voice_at(t)
        src, rect, ss = TILES[c['src']]
        if not v or v['src_key'] != src or t - v['at_s'] < 5 or v['at_s'] + (v['t1'] - v['t0']) - t < 5:
            continue
        s_audio = v['t0'] + (t - v['at_s'])
        s_video = (c['srcStart'] + (f - c['from'])) / FPS + ss
        out.append({'frame': f, 't': t, 'src_key': src, 's_audio': s_audio, 's_video_edl': s_video, 'cam': c['src']})
    return out


def pcm(path, ss, dur):
    raw = run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', f'{ss:.3f}', '-t', f'{dur:.3f}', '-i', str(path), '-vn', '-ac', '1', '-ar', '8000',
               '-f', 's16le', '-'], binary=True)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32)


def xcorr_lag(a, b, maxlag):
    """lag L (samples) maximising corr(a[n], b[n+L]); a is the reference window centred in b."""
    a = (a - a.mean()) / (a.std() + 1e-9)
    best, bl = -1e9, 0
    n = len(a)
    for L in range(-maxlag, maxlag + 1):
        s = maxlag + L
        seg = b[s:s + n]
        if len(seg) < n:
            continue
        seg = (seg - seg.mean()) / (seg.std() + 1e-9)
        c = float(np.dot(a, seg) / n)
        if c > best:
            best, bl = c, L
    return bl, best


def motion(path, ss, dur, crop, size=(64, 36)):
    w, h = size
    vf = f'crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]},scale={w}:{h},format=gray'
    raw = run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', f'{ss:.3f}', '-t', f'{dur:.3f}', '-i', str(path), '-vf', vf, '-r', str(FPS),
               '-f', 'rawvideo', '-'], binary=True)
    fr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w).astype(np.float32)
    return np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))


def sync_points(has_audio):
    cand = candidates()
    rnd = random.Random(2309)
    pts = sorted(rnd.sample(cand, min(npts, len(cand))), key=lambda p: p['t'])
    cam_rect = T['layout']['studio']['cam']
    res = []
    for p in pts:
        t_local = p['t'] - F0 / FPS
        src_file = J.src(p['src_key'])
        r = dict(p, t_tc=f"{int(p['t'] // 3600)}:{int(p['t'] % 3600 // 60):02d}:{p['t'] % 60:05.2f}")
        r['edl_audio_video_delta_ms'] = round((p['s_video_edl'] - p['s_audio']) * 1000, 1)
        if has_audio:
            ref = pcm(VIDEO, t_local - 2.0, 4.0)
            win = pcm(src_file, p['s_audio'] - 2.5, 5.0)
            lag, c = xcorr_lag(ref, win, 4000)  # +-0.5 s at 8 kHz
            r['audio_offset_ms'] = round(lag / 8.0, 1)
            r['audio_corr'] = round(c, 3)
        mf = motion(VIDEO, t_local - 3.0, 6.0, cam_rect)  # final cam window vs 4K source tile; ref 6 s, search +-12 f
        ms = motion(src_file, p['s_audio'] - 3.48, 6.96, TILES[p['cam']][1])
        lag, c = xcorr_lag(mf, ms, 12)
        r['video_lag_frames'] = lag
        r['video_corr'] = round(c, 3)
        if 'audio_offset_ms' in r:
            r['av_sync_ms'] = round(lag * 1000 / FPS - r['audio_offset_ms'], 1)  # + = picture ahead of the voice
        res.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    return res, len(cand)


def main():
    rep = {'video': str(VIDEO)}
    pr = probe()
    rep['probe'] = pr
    v = next(s for s in pr['streams'] if s['codec_type'] == 'video')
    a = next((s for s in pr['streams'] if s['codec_type'] == 'audio'), None)
    rep['frames'] = int(v['nb_read_packets'])
    rep['frames_expected'] = F1 - F0
    rep['duration_expected_s'] = (F1 - F0) / FPS
    print('frames', rep['frames'], 'expected', rep['frames_expected'], v['codec_name'], v.get('profile'), v['width'], v['height'], v['r_frame_rate'],
          'audio', a and (a['codec_name'], a['sample_rate'], a['channels'], a.get('duration')), 'format', pr['format'].get('duration'),
          pr['format'].get('bit_rate'), flush=True)
    if a:
        rep['loudness'] = loudness()
        print('loudness', rep['loudness'], flush=True)
    sync, ncand = sync_points(bool(a))
    rep['sync'] = sync
    rep['sync_candidates'] = ncand
    blacks, sil = black_and_silence(bool(a))
    rep['black'] = [{'start': b[0] + F0 / FPS, 'end': b[1] + F0 / FPS} for b in blacks]
    rep['silence'] = [{'start': s[0] + F0 / FPS, 'end': (s[1] + F0 / FPS) if s[1] is not None else None} for s in sil]
    print('black', rep['black'], flush=True)
    print('silence', rep['silence'], flush=True)
    out = Path(J.p('final/verify_report.json') if not chunk else J.p(f'render/qa/verify_chunk_{chunk}.json'))
    if '--report' in args:
        out = Path(args[args.index('--report') + 1])
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print('report', out)


if __name__ == '__main__':
    main()
