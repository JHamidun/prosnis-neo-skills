"""Remove the soundtrack delay that the Remotion render leaves in its mp4, then loudnorm the result.

Why: the AAC track Remotion writes starts at pts=0 with no edit list / skip_samples, so the encoder's
priming samples play as content and the whole soundtrack lags the picture. Measured 24.09 on s5
against the 4K Zoom source in three separate windows: voice.wav 0 ms, s5_raw.mp4 -42.7 ms
(= exactly 2048 samples at 48 kHz), identical in every window. The later ffmpeg AAC pass adds nothing
(ffmpeg marks its own priming with skip_samples).

    python tools/fix_av.py <raw.mp4> <final.mp4> [--samples 2048]

Video stream is copied untouched; audio: drop the leading samples, pad/trim to the video length,
two-pass loudnorm -16 LUFS / -1.5 dBTP (linear), AAC 192k 48 kHz, +faststart. Runs at BELOW_NORMAL.
"""
import argparse
import json
import re
import subprocess

LOW = getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)


def run(args):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=LOW)


def video_duration(path):
    r = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=duration', '-of', 'csv=p=0', path])
    return float(r.stdout.strip().split(',')[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('raw')
    ap.add_argument('final')
    ap.add_argument('--samples', type=int, default=2048, help='leading audio samples (48 kHz) to drop')
    a = ap.parse_args()
    dur = video_duration(a.raw)
    shift = (f'aresample=48000,atrim=start_sample={a.samples},asetpts=PTS-STARTPTS,'
             f'apad=whole_dur={dur:.6f},atrim=end={dur:.6f}')
    r = run(['ffmpeg', '-hide_banner', '-i', a.raw, '-vn', '-af',
             shift + ',loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
    m = json.loads(re.findall(r'\{[^{}]+\}', r.stderr)[-1])
    ln = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    r = run(['ffmpeg', '-y', '-hide_banner', '-v', 'error', '-i', a.raw, '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
             '-af', f'{shift},{ln}', '-ar', '48000', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', a.final])
    if r.returncode:
        raise SystemExit(r.stderr)
    r = run(['ffmpeg', '-hide_banner', '-i', a.final, '-vn', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json',
             '-f', 'null', '-'])
    f = json.loads(re.findall(r'\{[^{}]+\}', r.stderr)[-1])
    print(json.dumps({'final': a.final, 'dropped_samples': a.samples, 'video_dur': dur,
                      'loudness_lufs': f['input_i'], 'true_peak': f['input_tp']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
