"""S12: full-programme audio mix from edl/audio_plan.json -> final/program_mix.wav (48 kHz stereo s16).

Same sound as the approved excerpts (mix_excerpt.py): voice = source pieces with a static gain (Zoom parts lifted to
the recorder level, G-A4), dialog chain (highpass 80 Hz, compressor -20 dB 2.5:1), 20 ms fades at every cut; music =
bed pieces with a volume envelope (alone ~ -20 LUFS, under voice 10 dB lower, 0.35 s ramps, 0.5 s fade in / 1 s fade
out; music only under the teaser, chapter cards and the outro); final TWO-PASS linear loudnorm (G-A2).

Layout that scales to 2 hours (G-A7): voice pieces never overlap -> ONE concat chain with exact silence gaps computed
in SAMPLES from at_s (no drift, no adelay/amix PTS trap G-A3); music pieces overlap only with a neighbour -> two
alternating concat chains. The final amix has 3 inputs.

Priority: under a full render (CPU 100 %) a BELOW_NORMAL ffmpeg got 0.05 of a core - the mix of the reference run
stalled for 37 minutes (G-A8). Default here is NORMAL; use --priority below only on an idle machine, or run the mix
before/after the render.

job.json: audio.target_lufs (-16), audio.true_peak (-1.5), audio.lra (11)
usage: python mix_full.py --job job.json [--measure-only] [--priority normal|below|above]
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
OUT = Path(J.p('final'))
OUT.mkdir(parents=True, exist_ok=True)
SR = 48000
PRIO = sys.argv[sys.argv.index('--priority') + 1] if '--priority' in sys.argv else 'normal'
FLAGS = {'below': 0x00004000, 'above': 0x00008000, 'normal': 0x00000020}
I_T, TP_T, LRA_T = J.get('audio.target_lufs', -16), J.get('audio.true_peak', -1.5), J.get('audio.lra', 11)


def run(cmd, log=None):
    kw = {'creationflags': FLAGS[PRIO]} if os.name == 'nt' else {}
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', **kw)
    if log:
        Path(log).write_text(p.stderr[-20000:], encoding='utf-8')
    if p.returncode:
        print(p.stderr[-3000:])
        sys.exit(f'ffmpeg failed: {cmd[:6]}')
    return p.stderr


def lufs(path):
    err = run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-af', 'ebur128=framelog=quiet', '-f', 'null', '-'])
    for line in err.splitlines()[::-1]:
        if line.strip().startswith('I:'):
            return float(line.split()[1])
    raise SystemExit('no LUFS for ' + str(path))


def build():
    a = json.load(open(J.p('edl/audio_plan.json'), encoding='utf-8'))
    dur = a['dur_s']
    total = round(dur * SR)
    inputs, filters = [], []
    n = 0

    def silence(samples, label):
        filters.append(f"anullsrc=r={SR}:cl=stereo,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=end_sample={samples},asetpts=N/SR/TB[{label}]")

    # ---- voice chain
    seg = []
    pos = 0
    for i, v in enumerate(a['voice']):
        start = round(v['at_s'] * SR)
        length = round((v['t1'] - v['t0']) * SR)
        if start > pos:
            silence(start - pos, f'vs{i}')
            seg.append(f'[vs{i}]')
            pos = start
        elif start < pos:  # overlap by rounding only -> trim head of this piece
            length -= (pos - start)
        d = length / SR
        inputs += ['-ss', f"{v['t0']:.4f}", '-t', f"{v['t1'] - v['t0'] + 0.1:.4f}", '-i', v['src']]
        filters.append(
            f"[{n}:a]aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB,atrim=end_sample={length},"
            f"volume={v.get('gain_db', 0):.2f}dB,highpass=f=80,acompressor=threshold=-20dB:ratio=2.5:attack=15:release=250,"
            f"afade=t=in:d=0.02,afade=t=out:st={max(0, d - 0.02):.4f}:d=0.02[vp{i}]")
        seg.append(f'[vp{i}]')
        pos += length
        n += 1
    if pos < total:
        silence(total - pos, 'vend')
        seg.append('[vend]')
    filters.append(f"{''.join(seg)}concat=n={len(seg)}:v=0:a=1,atrim=end_sample={total}[voice]")

    # ---- music chains (alternating so neighbours can overlap)
    music_src = a['music'][0]['src']
    g_alone = -20.0 - lufs(music_src)
    g_duck = g_alone - 10
    ga, gd = 10 ** (g_alone / 20), 10 ** (g_duck / 20)
    print('music gain alone', round(g_alone, 2), 'dB')
    chains = {0: [], 1: []}
    cpos = {0: 0, 1: 0}
    for j, m in enumerate(a['music']):
        ch = j % 2
        at, to = m['at_s'], m['to_s']
        start = round(at * SR)
        length = round((to - at) * SR)
        if start > cpos[ch]:
            silence(start - cpos[ch], f'ms{j}')
            chains[ch].append(f'[ms{j}]')
        L = length / SR
        a0 = m.get('alone_from_s', at) - at
        a1 = m.get('alone_until_s', to) - at
        r = 0.35
        expr = (f"if(lt(t,{a0 - r:.3f}),{gd:.5f},if(lt(t,{a0:.3f}),{gd:.5f}+({ga:.5f}-{gd:.5f})*(t-{a0 - r:.3f})/{r},"
                f"if(lt(t,{a1:.3f}),{ga:.5f},if(lt(t,{a1 + r:.3f}),{ga:.5f}-({ga:.5f}-{gd:.5f})*(t-{a1:.3f})/{r},{gd:.5f}))))")
        inputs += ['-ss', f"{m['from_s']:.4f}", '-t', f'{L + 0.1:.4f}', '-i', m['src']]
        filters.append(
            f"[{n}:a]aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB,atrim=end_sample={length},"
            f"volume='{expr}':eval=frame,afade=t=in:d=0.5,afade=t=out:st={max(0, L - 1.0):.4f}:d=1.0[mp{j}]")
        chains[ch].append(f'[mp{j}]')
        cpos[ch] = start + length
        n += 1
    for ch in (0, 1):
        if cpos[ch] < total:
            silence(total - cpos[ch], f'mend{ch}')
            chains[ch].append(f'[mend{ch}]')
        filters.append(f"{''.join(chains[ch])}concat=n={len(chains[ch])}:v=0:a=1,atrim=end_sample={total}[music{ch}]")
    filters.append('[voice][music0][music1]amix=inputs=3:normalize=0:duration=longest,atrim=end_sample=%d' % total)
    return inputs, filters, dur


def main():
    inputs, filters, dur = build()
    (OUT / 'mix_filter.txt').write_text(';\n'.join(filters), encoding='utf-8', newline='\n')
    head = ';'.join(filters)
    err = run(['ffmpeg', '-hide_banner', '-nostats', '-y', *inputs, '-filter_complex',
               head + f',loudnorm=I={I_T}:TP={TP_T}:LRA={LRA_T}:print_format=json[out]', '-map', '[out]', '-f', 'null', '-'],
              log=OUT / 'mix_pass1.log')
    js = json.loads(err[err.rindex('{'):err.rindex('}') + 1])
    print('pass1', js)
    if '--measure-only' in sys.argv:
        return
    ln = (f"loudnorm=I={I_T}:TP={TP_T}:LRA={LRA_T}:measured_I={js['input_i']}:measured_TP={js['input_tp']}:measured_LRA={js['input_lra']}:"
          f"measured_thresh={js['input_thresh']}:offset={js['target_offset']}:linear=true:print_format=json")
    wav = OUT / 'program_mix.wav'
    err = run(['ffmpeg', '-hide_banner', '-nostats', '-y', *inputs, '-filter_complex', head + ',' + ln + '[out]', '-map', '[out]',
               '-ar', str(SR), '-c:a', 'pcm_s16le', str(wav)], log=OUT / 'mix_pass2.log')
    js2 = json.loads(err[err.rindex('{'):err.rindex('}') + 1])
    # pass 2 may fall back to "dynamic" when the measured LRA/TP do not allow a linear gain (reference run: dynamic,
    # still -16.0 LUFS / -1.5 dBTP, LRA 3.3) - the numbers below are the check, not the mode
    print('pass2', js2.get('normalization_type'), 'out I', js2.get('output_i'), 'TP', js2.get('output_tp'))
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(wav)], capture_output=True, text=True).stdout.strip()
    got = lufs(wav)
    print('OK', wav, 'dur', probe, 'target', dur, 'LUFS', got)
    if abs(float(probe) - dur) > 0.05 or abs(got - I_T) > 0.3:
        sys.exit(f'mix check failed: duration {probe} vs {dur}, LUFS {got} vs {I_T}')


if __name__ == '__main__':
    main()
