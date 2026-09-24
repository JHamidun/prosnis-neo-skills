"""S12/S13: mix the audio of a SHORT excerpt (a showcase, a test EDL, a story) and mux it with its rendered video.

voice: source segments placed on the output clock with 20 ms fades at every cut, dialog chain (highpass 80,
compressor -20 dB 2.5:1); music: bed with a volume envelope (alone ~ -20 LUFS, under voice ~10 dB lower, 0.35 s ramps,
0.5 s fade in / 1 s fade out); final two-pass linear loudnorm (-16 LUFS / -1.5 dBTP by default).

The adelay/amix trap (G-A3): with several inputs amix starts the OUTPUT at the PTS of the earliest input, so a mix
whose first voice piece starts at 8 s came out 8 s short and the voice moved. Every branch here is re-timed with
asetpts=PTS-STARTPTS+<at>/TB, aresample=48000:async=1:first_pts=0 (fills the head with silence) and apad=whole_dur.

audio json: {"dur_s": 44.5,
             "voice": [{"at": 0.0, "src": "<file>", "t0": 12.3, "t1": 18.9}],
             "music": [{"src": "<bed.wav>", "at": 0.0, "to": 23.3, "from_s": 7.8, "alone_from": 0.0, "alone_until": 7.7}]}
usage: python mix_excerpt.py --job job.json <audio.json> <video.mp4> <out.mp4>
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load, low_flags  # noqa: E402

J = load()
I_T, TP_T = J.get('audio.target_lufs', -16), J.get('audio.true_peak', -1.5)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', **low_flags())
    if p.returncode:
        print(p.stderr[-3000:])
        sys.exit(f'ffmpeg failed: {cmd[:6]}')
    return p.stderr


def lufs(path):
    err = run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-af', 'ebur128=framelog=quiet', '-f', 'null', '-'])
    for line in err.splitlines()[::-1]:
        if line.strip().startswith('I:'):
            return float(line.split()[1])
    return -20.0


def mix(audio_json, video, final):
    a = json.load(open(audio_json, encoding='utf-8'))
    dur = a['dur_s']
    inputs, filters, labels = [], [], []
    n = 0
    g_alone = None
    for v in a['voice']:
        inputs += ['-ss', f"{v['t0']:.3f}", '-t', f"{v['t1'] - v['t0']:.3f}", '-i', v['src']]
        d = v['t1'] - v['t0']
        filters.append(
            f"[{n}:a]asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,{'volume=%.2fdB,' % v['gain_db'] if v.get('gain_db') else ''}highpass=f=80,"
            f"acompressor=threshold=-20dB:ratio=2.5:attack=15:release=250,"
            f"afade=t=in:d=0.02,afade=t=out:st={max(0, d - 0.03):.3f}:d=0.03,asetpts=PTS-STARTPTS+{v['at']:.3f}/TB,"
            f"aresample=48000:async=1:first_pts=0,apad=whole_dur={dur:.3f}[v{n}]")
        labels.append(f'[v{n}]')
        n += 1
    for m in a.get('music', []):
        if g_alone is None:
            g_alone = -20.0 - lufs(m['src'])
            print('music gain for -20 LUFS alone:', round(g_alone, 2), 'dB')
        g_duck = g_alone - 10
        at, to = m['at'], m['to']
        length = to - at
        inputs += ['-ss', f"{m['from_s']:.3f}", '-t', f'{length:.3f}', '-i', m['src']]
        a0 = m.get('alone_from', at) - at  # envelope in LOCAL time of the music clip
        a1 = m.get('alone_until', to) - at
        ga = 10 ** (g_alone / 20)
        gd = 10 ** (g_duck / 20)
        r = 0.35
        expr = (f"if(lt(t,{a0 - r:.3f}),{gd:.5f},if(lt(t,{a0:.3f}),{gd:.5f}+({ga:.5f}-{gd:.5f})*(t-{a0 - r:.3f})/{r},"
                f"if(lt(t,{a1:.3f}),{ga:.5f},if(lt(t,{a1 + r:.3f}),{ga:.5f}-({ga:.5f}-{gd:.5f})*(t-{a1:.3f})/{r},{gd:.5f}))))")
        filters.append(
            f"[{n}:a]asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume='{expr}':eval=frame,"
            f"afade=t=in:d=0.5,afade=t=out:st={max(0, length - 1.0):.3f}:d=1.0,asetpts=PTS-STARTPTS+{at:.3f}/TB,"
            f"aresample=48000:async=1:first_pts=0,apad=whole_dur={dur:.3f}[m{n}]")
        labels.append(f'[m{n}]')
        n += 1
    base = f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,atrim=0:{dur:.3f},"
    # pass 1: measure the whole mix; pass 2: linear loudnorm with the measured values (no pumping, G-A2)
    err = run(['ffmpeg', '-hide_banner', '-y', *inputs, '-filter_complex',
               ';'.join(filters + [base + f'loudnorm=I={I_T}:TP={TP_T}:LRA=8:print_format=json[out]']), '-map', '[out]', '-f', 'null', '-'])
    js = json.loads(err[err.rindex('{'):err.rindex('}') + 1])
    ln = (f"loudnorm=I={I_T}:TP={TP_T}:LRA=8:measured_I={js['input_i']}:measured_TP={js['input_tp']}:measured_LRA={js['input_lra']}:"
          f"measured_thresh={js['input_thresh']}:offset={js['target_offset']}:linear=true")
    final = Path(final)
    wav = final.with_suffix('.mix.wav')
    run(['ffmpeg', '-hide_banner', '-y', *inputs, '-filter_complex', ';'.join(filters + [base + ln + '[out]']), '-map', '[out]', '-ar', '48000',
         '-c:a', 'pcm_s16le', str(wav)])
    run(['ffmpeg', '-hide_banner', '-y', '-i', str(video), '-i', str(wav), '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac',
         '-b:a', '192k', '-shortest', '-movflags', '+faststart', str(final)])
    print('OK', final, 'LUFS', lufs(final))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    mix(*sys.argv[1:4])
