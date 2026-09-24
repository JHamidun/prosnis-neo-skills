"""Write <job>/timeline.json - master timeline of the webinar from the reference recorder (Plaud-type device =
reference clock) and the Zoom/stream parts. All numbers come from align/*.json results (see 'evidence');
rerun is idempotent. timeline.json is the CONTRACT of every later stage (schema in its 'how_to_read').

Inputs (job):
  job.json            align.reference / align.parts / align.t0_wall (recorder device start, ISO with tz) /
                      align.chat_clock_offset_s (+ _err_s), sources[] (paths, durations, recorder file_id)
  align/dense_*.json  -> offmap.OffMap knots per part
  align/align_config.json "pieces"          recorder-only pieces {name: [plaud_in, plaud_out]} (process_recorder.py)
  align/timeline_config.json               the EDITORIAL part, written by the aligning agent after listening:
      "title", "segments": [[source, src_in, src_out, recommended, kind(main|optional|skip), note], ...] in air order,
      "head_knots": {part: {"replace_until": 17.5, "knots": [[t, offset], ...]}}  (junction.py results that replace
                    the first dense knots), "visual_cues_intro": [...], "clock": {"evidence": [...], "chat_caveat": ".."},
      "offsets": {...hand-written summaries merged over the computed ones}, "method": "..", "loudness": {...},
      "notes": [...]
  align/verify_listen.json, align/process_plaud.json
usage: python build_timeline.py --job job.json
"""
import datetime
import json
import pathlib

import numpy as np

from offmap import OffMap

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()

R = pathlib.Path(J.root)
A = R / "align"
CFG = J.data("align/timeline_config.json")
C_SEC, C_ERR = float(J.get("align.chat_clock_offset_s", 0.0)), float(J.get("align.chat_clock_err_s", 1.0))
PLAUD_T0 = datetime.datetime.fromisoformat(J.need("align.t0_wall"))
WALL0 = PLAUD_T0 + datetime.timedelta(seconds=C_SEC)
PIECES = {k: tuple(v) for k, v in J.data("align/align_config.json", {}).get("pieces", {}).items()}
PARTS = J.parts()
REF = J.ref_id()
HEAD = CFG.get("head_knots", {})


def knots(part):
    m = OffMap(part)
    t, o = list(m.t), list(m.o)
    h = HEAD.get(part)
    if h:
        # junction-level offsets (align/junction.json, W1.5 step 0.25 GCC-PHAT) replace the coarse first knots
        keep = [(a, b) for a, b in zip(t, o) if a > h["replace_until"]]
        pts = [tuple(x) for x in h["knots"]] + keep
    else:
        pts = list(zip(t, o))
    return [[round(float(a), 3), round(float(b), 4)] for a, b in pts]


K = {p: knots(p) for p in PARTS}


def plaud_of(src, t):
    if src == "plaud":
        return t
    if src in PIECES:
        return PIECES[src][0] + t
    k = np.array(K[src])
    return float(t + np.interp(t, k[:, 0], k[:, 1]))


def wall(p):
    return (WALL0 + datetime.timedelta(seconds=p)).strftime("%H:%M:%S.%f")[:-4]


def files():
    out = {}
    for p in PARTS:
        out[p] = {"video": J.p("proxy", f"{p}.mp4"), "audio16k": J.p("audio", f"{p}_16k.wav"), "original": J.src(p),
                  "duration": round(J.dur(p), 3), "words": J.p("transcript", f"{p}.words.json")}
    for i, (n, (a, b)) in enumerate(PIECES.items()):
        out[n] = {"audio": J.p("audio", f"{n}.wav"), "audio16k": J.p("audio", f"{n}_16k.wav"), "duration": round(b - a, 3),
                  "plaud_in": a, "words": J.p("transcript", "plaud_intro.words.json") + ("" if i == 0 else f"#{n.replace('_plaud', '')}")}
    out["plaud"] = {"audio": J.src(REF), "audio16k": J.p("audio", "plaud_16k.wav"), "duration": round(J.dur(REF), 2),
                    "plaud_file_id": J.source(REF).get("file_id")}
    return out


def merge(a, b):
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            merge(a[k], v)
        else:
            a[k] = v
    return a


def offsets():
    res = {}
    for p in PARTS:
        k = np.array(K[p])
        dur = J.dur(p)
        st, en = plaud_of(p, 0.0), plaud_of(p, dur)
        steps = int((np.abs(np.diff(k[:, 1])) > 0.03).sum())
        res[p] = {"start_in_plaud": round(st, 3), "end_offset": round(float(k[-1, 1]), 3), "end_in_plaud": round(en, 3),
                  "wall_start_msk": wall(st), "wall_end_msk": wall(en), "net_drift_s": round(float(k[-1, 1] - k[0, 1]), 3),
                  "steps_gt_30ms": steps}
    for a, b in zip(PARTS, PARTS[1:]):
        g0, g1 = res[a]["end_in_plaud"], res[b]["start_in_plaud"]
        res[f"{a}_to_{b}"] = {"overlap": g1 < g0, "gap_s": round(g1 - g0, 2), "gap_plaud": [g0, g1]}
    merge(res, CFG.get("offsets"))
    for p in PARTS:  # wall clock strings follow the (possibly overridden) plaud numbers
        res[p]["wall_start_msk"] = wall(res[p]["start_in_plaud"])
        res[p]["wall_end_msk"] = wall(res[p]["end_in_plaud"])
    res["part_to_plaud_knots"] = K
    return res


def main():
    FILES = files()
    segs, tl = [], 0.0
    for (src, a, b, rec, kind, note) in CFG["segments"]:
        pa, pb = plaud_of(src, a), plaud_of(src, b)
        d = {"source": src, "file": FILES[src].get("video") or FILES[src].get("audio"), "has_video": src in PARTS,
             "src_in": round(a, 3), "src_out": round(b, 3), "duration": round(b - a, 3),
             "plaud_in": round(pa, 3), "plaud_out": round(pb, 3), "wall_start_msk": wall(pa), "wall_end_msk": wall(pb),
             "recommended": rec, "kind": kind, "note": note}
        if rec:
            d["edit_in"], d["edit_out"] = round(tl, 3), round(tl + (b - a), 3)
            tl += b - a
        segs.append(d)
    ref_dur = J.dur(REF)
    clock = CFG.get("clock", {})
    out = {
        "title": CFG.get("title") or f"{J.get('title', '')} — мастер-таймлайн",
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "builder": pathlib.Path(__file__).as_posix(),
        "how_to_read": {
            "segments": "в порядке эфира; recommended=true — рекомендуемый монтаж (edit_in/edit_out — позиция в итоговом ролике до "
                        "внутренних сокращений), recommended=false — есть в записи, но по умолчанию вырезано (kind optional/skip)",
            "src_in/src_out": "секунды от начала файла source (для частей — одинаково для прокси и оригинала)",
            "plaud_t": "секунды от начала записи диктофона (эталонная шкала)",
            "wall_msk": "московское время = wall_zero_msk + plaud_t; точность ±C_err_s (см. clock)",
            "part→plaud": "plaud_t = t + offset(t), offset — кусочно-постоянная (скачки при сбоях сети Zoom), здесь узлы для линейной "
                          "интерполяции (np.interp); между узлами, далеко отстоящими друг от друга, положение скачка известно до ±половины интервала",
        },
        "files": FILES,
        "plaud": merge({
            "file_id": J.source(REF).get("file_id"), "start_time_ms": int(round(PLAUD_T0.timestamp() * 1000)),
            "device_start_msk": PLAUD_T0.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], "duration_s": round(ref_dur, 2),
            "device_end_msk": (PLAUD_T0 + datetime.timedelta(seconds=ref_dur)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        }, CFG.get("recorder_meta")),
        "clock": {
            "C_s": C_SEC, "C_err_s": C_ERR, "wall_zero_msk": WALL0.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "formula": f"wall_msk = {WALL0.strftime('%H:%M:%S.%f')[:-3]} + plaud_t  (= recorder device clock + {C_SEC} s)",
            "zoom_vs_plaud_sample_clocks": clock.get("sample_clocks", "совпадают <1 ppm; расхождения только ступеньками (провалы Zoom)"),
            "evidence": clock.get("evidence", []),
            "chat_caveat": clock.get("chat_caveat", "метки времени в сохранённом чате — часы УСТРОЙСТВА отправителя (порядок в файле = порядок прихода). "
                                                    "Для оверлея: порядок прихода + монотонное сглаживание меток (backward-min, затем forward-max)."),
            "confidence": clock.get("confidence", f"MEDIUM (±{C_ERR} s)"),
        },
        "offsets": offsets(),
        "alignment_confidence": {
            "sample_level": CFG.get("sample_level", "HIGH"),
            "method": CFG.get("method", "огибающие 16 кГц → грубая взаимная корреляция (xcorr.py), затем плотный GCC-PHAT (dense.py, окно 10 с шаг 10 с, "
                                        "±6 с) и на стыках окно 1.5 с шаг 0.25 с (junction.py); проверка на слух — verify_listen.py"),
            "verify_windows": json.loads((A / "verify_listen.json").read_text(encoding="utf-8")),
            "wall_clock": f"MEDIUM ±{C_ERR} s",
        },
        "audio_pieces": json.loads((A / "process_plaud.json").read_text(encoding="utf-8")),
        "loudness": CFG.get("loudness", {}),
        "visual_cues_intro": CFG.get("visual_cues_intro", []),
        "total_recommended_s": round(tl, 3),
        "total_recommended_hms": str(datetime.timedelta(seconds=round(tl))),
        "segments": segs,
        "notes": CFG.get("notes", []),
    }
    (R / "timeline.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in segs:
        print(f"{'REC ' if s['recommended'] else '    '}{s['source']:12s} {s['src_in']:9.3f}-{s['src_out']:9.3f} "
              f"plaud {s['plaud_in']:9.3f}-{s['plaud_out']:9.3f}  {s['wall_start_msk']}-{s['wall_end_msk']}  "
              f"edit {s.get('edit_in', '')}-{s.get('edit_out', '')}")
    print("total", out["total_recommended_hms"], "knots", {p: len(K[p]) for p in PARTS})


if __name__ == "__main__":
    main()
