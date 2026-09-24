"""Stage 6 (v2): build scenes.json.

Segment boundaries come from the dense frame pass (every 2 s, deduped visual states classified
by Gemini 3.8 Flash), refined to frame accuracy (bounds_<tag>.json). Semantics (what happens,
beats, energy, highlights, problems) come from the Gemini video pass v2 (raw_v2/). Speaker and
speech density come from the corrected Deepgram transcript. Camera tiles come from deterministic
pixel analysis of the Zoom strip (tiles_<tag>.json). Sensitive data comes from the focused
privacy pass over every 2-s frame (sens_raw/) + the video pass.

Everything that is a DECISION about this particular webinar (each verified by looking at a 4K frame or by the
transcript) lives in <job>/vision/vision_overrides.json - never in code:
  video_slides        deck slides with an embedded video (also job.json deck.video_slides)
  team_names          lowercase name fragments of the team: their name labels in Zoom tiles are not private
  owner_handles       public @handles of the owner (not a leak)
  cams                {"host": "<short name>", "cohost": "<short name>"} - who sits in strip slot 1 / slot 2
  overrides           [[tag, from, to, [kind, slide|null], why]]      whole-run relabels (embedded video, placeholder)
  manual_slides       [[tag, start, end, slide, note]]                sub-second slide flips (G-V4)
  sens_resolve        [[tag, t_lo, t_hi, [types], t_in, t_out, severity, on_slide, note]] verdicts on video-pass-only items
  sens_audio          [{source, t_in, t_out, type: spoken_full_name, ...}]   personal data SAID aloud
  hl_fix              [[tag, round(raw t_in), best_in|null, best_out|null, note]]  highlights anchored to words by hand
  events              [[tag, t_in, t_out, description, note]]         moments anchored to transcript words (raffle spins)
  event_type          type of those moments (reference: "drum_spin"), event_content ("raffle_app")
  pick                [[tag, "HH:MM:SS"]]                              curated highlights (video-pass raw t_in)
  continuity_notes    {"note": "...", "missing_start": "..."}
Zoom strip geometry: job.json zoom.strip (same as tiles.py).
usage: python build_scenes.py --job job.json -> vision/scenes.json
"""
import difflib
import glob
import json
import os
import re
import statistics
from collections import Counter, defaultdict

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
ROOT = f"{J.root}/vision"
TR = f"{J.root}/transcript"
TAGS = J.vision_tags()  # {"P1": "part1", ...}
SOURCES = {tag: J.src(sid) for tag, sid in TAGS.items()}
DUR = {tag: J.dur(sid) for tag, sid in TAGS.items()}
W4K, H4K = 3840, 2160
DECK = {s["n"]: s["title"] for s in json.load(open(f"{ROOT}/deck_titles.json", encoding="utf-8"))}
VO = J.data("vision/vision_overrides.json", {})
VIDEO_SLIDES = set(VO.get("video_slides") or J.get("deck.video_slides", []))
TEAM_NAMES = tuple(VO.get("team_names", []))
OWNER_HANDLES = [h.lower().lstrip("@") for h in VO.get("owner_handles", [])]
CAM = {"host": VO.get("cams", {}).get("host", "ведущий"), "cohost": VO.get("cams", {}).get("cohost", "со-ведущий")}
SPK_SHORT = {J.get(f"speakers.{k}.name"): v for k, v in CAM.items() if J.get(f"speakers.{k}.name")}
# Zoom strip geometry measured on 4K frames (vision/probe/*_strip.png)
STRIP = J.need("zoom.strip")
# Manual overrides, each verified by looking at the frame named in the note.
OVERRIDES = [(o[0], o[1], o[2], tuple(o[3]), o[4]) for o in VO.get("overrides", [])]
# Sub-second slide flips the 2-s frame pass cannot resolve (packet-size peak in the 4K stream + frame check).
MANUAL_SLIDES = [tuple(x) for x in VO.get("manual_slides", [])]
# Verdicts on items only the video pass reported, each after looking at a readable 4K frame.
SENS_RESOLVE = [(x[0], x[1], x[2], tuple(x[3]), x[4], x[5], x[6], x[7], x[8]) for x in VO.get("sens_resolve", [])]
# Spoken personal data (audio, not screen) found while anchoring highlights in the transcript.
SENS_AUDIO = VO.get("sens_audio", [])
# Highlights whose quote is slide text (not speech): timing anchored by hand to the transcript words.
HL_FIX = {(x[0], x[1]): (x[2], x[3], x[4]) for x in VO.get("hl_fix", [])}
# moments anchored to transcript words (reference webinar: the raffle "drum" spins)
EVENTS = [tuple(x) for x in VO.get("events", [])]
EVENT_TYPE = VO.get("event_type", "drum_spin")
EVENT_CONTENT = VO.get("event_content", "raffle_app")


def hms(t):
    t = max(0.0, float(t))
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h:02d}:{m:02d}:{t - h * 3600 - m * 60:04.1f}"


def to_sec(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"^(\d+):(\d{1,2}):(\d{1,2}(?:[.,]\d+)?)$", str(v).strip())
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3).replace(",", "."))
    m = re.match(r"^(\d+):(\d{1,2}(?:[.,]\d+)?)$", str(v).strip())
    if m:
        return int(m.group(1)) * 60 + float(m.group(2).replace(",", "."))
    return None


def box_out(b, w=W4K, h=H4K):
    """[ymin,xmin,ymax,xmax] 0..1000 -> dict with norm xyxy + 4K px xywh."""
    if not b:
        return None
    y0, x0, y1, x1 = b
    return {"norm_xyxy": [round(x0 / 1000, 4), round(y0 / 1000, 4), round(x1 / 1000, 4), round(y1 / 1000, 4)],
            "px_4k_xywh": [round(x0 / 1000 * w), round(y0 / 1000 * h), round((x1 - x0) / 1000 * w),
                           round((y1 - y0) / 1000 * h)]}


def px_box(x0, y0, x1, y1):
    return {"norm_xyxy": [round(x0 / W4K, 4), round(y0 / H4K, 4), round(x1 / W4K, 4), round(y1 / H4K, 4)],
            "px_4k_xywh": [round(x0), round(y0), round(x1 - x0), round(y1 - y0)]}


def valid_box(b):
    return (isinstance(b, list) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b)
            and b[2] > b[0] and b[3] > b[1] and min(b) >= 0 and max(b) <= 1000)


# ------------------------------------------------------------------ inputs
def frame_states(tag):
    st = []
    for f in sorted(glob.glob(f"{ROOT}/frames_raw/{tag}_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        bk = {}
        for x in d["result"].get("frames", []):
            try:
                bk[int(x.get("k"))] = x
            except (TypeError, ValueError):
                pass
        for it in d["items"]:
            x = bk.get(it["k"])
            if x is not None:
                st.append({"t": it["t"], "t_end": it["t_end"], "file": it["file"], **x})
    st.sort(key=lambda s: s["t"])
    return st


def norm_key(tag, s):
    for otag, a, b, key, _ in OVERRIDES:
        if otag == tag and a <= s["t"] < b:
            return key
    lay, sk, sn = s.get("layout"), s.get("share_kind"), s.get("slide_number")
    desc = s.get("screen_desc") or ""
    try:
        sn = int(sn) if sn not in (None, "", "null") else None
    except (TypeError, ValueError):
        sn = None
    if lay == "speaker_cam_full":
        return ("camera", None)
    if sn is None and (lay == "drum_raffle" or re.search(r"розыгрыш|барабан|рулетк", desc, re.I)):
        return ("raffle", None)
    if sn is not None and sk != "none":
        return ("slide", sn)
    if sk == "none" or lay == "waiting_screen":
        return ("black", None)
    return ("demo", None)


def load_video_pass(tag):
    segs, hls, pbs, sens = [], [], [], []
    for f in sorted(glob.glob(f"{ROOT}/raw_v2/{tag}_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        s0, e0, r = d["start"], d["end"], d["result"]
        for sg in r.get("segments", []):
            a, b = to_sec(sg.get("src_in")), to_sec(sg.get("src_out"))
            if a is None or b is None:
                continue
            a, b = max(a, s0), min(b, e0)
            if b - a >= 0.5:
                segs.append({**sg, "a": a, "b": b, "chunk": d["idx"]})
        for h in r.get("highlights", []):
            a, b = to_sec(h.get("t_in")), to_sec(h.get("t_out"))
            if a is not None:
                hls.append({**h, "source": tag, "a": a, "b": b if b and b > a else a + 5, "chunk": d["idx"]})
        for p in r.get("problems", []):
            a, b = to_sec(p.get("t_in")), to_sec(p.get("t_out"))
            if a is not None:
                pbs.append({**p, "source": tag, "a": a, "b": b if b and b > a else a + 3, "chunk": d["idx"]})
        for x in r.get("sensitive", []):
            a, b = to_sec(x.get("t_in")), to_sec(x.get("t_out"))
            if a is not None:
                sens.append({**x, "source": tag, "a": a, "b": b if b and b > a else a + 2, "chunk": d["idx"]})
    return segs, hls, pbs, sens


def slide_of(v):
    try:
        return int(v.get("slide_number")) if v.get("slide_number") not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def compute_warp(vsegs, runs):
    """Video-pass timecodes drift (measured up to ~35 s). Anchor every video-pass slide change to the
    frame-accurate start of the same slide in the frame pass; offsets are interpolated per chunk."""
    starts = defaultdict(list)
    for i, r in enumerate(runs):
        k = r["key"]
        if i == 0 or runs[i - 1]["key"] != k:
            starts[k].append(r["src_in"])
    anchors = defaultdict(list)
    by_chunk = defaultdict(list)
    for v in vsegs:
        by_chunk[v["chunk"]].append(v)
    for ch, lst in by_chunk.items():
        lst.sort(key=lambda v: v["a"])
        for i, v in enumerate(lst):
            sn = slide_of(v)
            lay = v.get("layout")
            if lay == "drum_raffle":
                key = ("raffle", None)
            elif lay == "speaker_cam_full":
                key = ("camera", None)
            elif sn is not None:
                key = ("slide", sn)
            else:
                continue
            prev_key = None
            if i > 0:
                p = lst[i - 1]
                prev_key = (("raffle", None) if p.get("layout") == "drum_raffle" else
                            ("camera", None) if p.get("layout") == "speaker_cam_full" else
                            ("slide", slide_of(p)) if slide_of(p) is not None else None)
            if i == 0 or prev_key == key:
                continue  # chunk start or intra-slide split: not an observed change
            cands = [t for t in starts.get(key, []) if abs(t - v["a"]) <= 60]
            if cands:
                t = min(cands, key=lambda t: abs(t - v["a"]))
                anchors[ch].append((v["a"], t - v["a"]))
    # drop isolated outliers (video pass mislabelled the slide): offset far from BOTH neighbours
    for ch in list(anchors):
        a = sorted(anchors[ch])
        keep = []
        for i, (t, o) in enumerate(a):
            nb = [a[j][1] for j in (i - 1, i + 1) if 0 <= j < len(a)]
            if nb and all(abs(o - x) > 10 for x in nb):
                continue
            keep.append((t, o))
        anchors[ch] = keep
    return anchors


def vkey(v):
    lay, sn = v.get("layout"), slide_of(v)
    if lay == "drum_raffle":
        return ("raffle", None)
    if lay == "speaker_cam_full":
        return ("camera", None)
    if lay == "waiting_screen":
        return ("placeholder", None)
    if sn is not None:
        return ("slide", sn)
    if lay == "other" or v.get("share_kind") == "none":
        return ("black", None)
    return ("demo", None)


def assign_local(runs, vsegs):
    """Give every frame run its own video-pass segments: a video segment goes to the run with the same
    content key (same slide number / demo / raffle ...) that it overlaps most (after warp), else to the
    nearest such run within 120 s. Each run's segments are then stretched onto the run's exact
    frame-pass span, which removes the video pass's timecode drift per slide."""
    by_key = defaultdict(list)
    for i, r in enumerate(runs):
        by_key[r["key"]].append(i)
    assigned = defaultdict(list)
    for v in vsegs:
        idx = by_key.get(vkey(v), [])
        best, bscore = None, None
        for i in idx:
            r = runs[i]
            ov = overlap(r["src_in"], r["src_out"], v["a"], v["b"])
            gap = 0 if ov > 0 else min(abs(v["a"] - r["src_out"]), abs(r["src_in"] - v["b"]))
            score = (ov, -gap)
            if gap <= 120 and (bscore is None or score > bscore):
                best, bscore = i, score
        if best is not None:
            assigned[best].append(v)
    for i, r in enumerate(runs):
        lst = sorted(assigned.get(i, []), key=lambda v: v["a"])
        a, b = r["src_in"], r["src_out"]
        if lst:
            first, last = lst[0]["a"], max(v["b"] for v in lst)
            k = (b - a) / (last - first) if last > first else 1.0

            def m(t, first=first, k=k, a=a):
                return a + (t - first) * k
            loc = []
            for v in lst:
                nv = dict(v)
                nv["a"], nv["b"] = m(v["a"]), m(v["b"])
                nv["beats"] = [{**bt, "t": m(to_sec(bt["t"]))} for bt in (v.get("beats") or [])
                               if to_sec(bt.get("t")) is not None]
                loc.append(nv)
            r["local"], r["local_how"] = loc, "content-matched to frame run (slide/demo/raffle), stretched onto its span"
        else:
            loc = []
            for v in vsegs:
                if overlap(a, b, v["a"], v["b"]) > 0:
                    nv = dict(v)
                    nv["beats"] = [{**bt, "t": to_sec(bt["t"])} for bt in (v.get("beats") or [])
                                   if to_sec(bt.get("t")) is not None]
                    loc.append(nv)
            r["local"], r["local_how"] = loc, "time overlap only (no content match; timing approximate)"
    return runs


def warp(anchors, ch, t):
    a = anchors.get(ch) or []
    if t is None or not a:
        return t
    if t <= a[0][0]:
        return t + a[0][1]
    if t >= a[-1][0]:
        return t + a[-1][1]
    for (t0, o0), (t1, o1) in zip(a, a[1:]):
        if t0 <= t <= t1:
            return t + (o0 + (o1 - o0) * (t - t0) / (t1 - t0) if t1 > t0 else o0)
    return t


def apply_warp(anchors, vsegs, hls, pbs, vsens):
    for v in vsegs:
        v["a_raw"], v["b_raw"] = v["a"], v["b"]
        v["a"], v["b"] = warp(anchors, v["chunk"], v["a"]), warp(anchors, v["chunk"], v["b"])
        for bt in v.get("beats") or []:
            t = to_sec(bt.get("t"))
            if t is not None:
                bt["t"] = warp(anchors, v["chunk"], t)
    for lst in (hls, pbs, vsens):
        for x in lst:
            x["a_raw"], x["b_raw"] = x["a"], x["b"]
            x["a"], x["b"] = warp(anchors, x["chunk"], x["a"]), warp(anchors, x["chunk"], x["b"])


def load_words(tag):
    d = json.load(open(f"{TR}/{TAGS[tag]}.words.json", encoding="utf-8"))
    return d["words"]


def load_tiles(tag):
    out = []
    for r in json.load(open(f"{ROOT}/tiles_{tag}.json")):
        s1, s2 = r["slots"][0], r["slots"][1]
        live1 = bool(s1 and s1[0] > 45 and 60 < s1[2] < 225 and 0.12 < s1[1] < 0.45)
        live2 = bool(s2 and s2[0] > 45 and 60 < s2[2] < 150 and 0.2 < s2[1] < 0.45)
        out.append((r["t"], live1, live2))
    # slot-2 "live" shorter than 30 s is slide content showing through (P1 05:08) -> drop
    res, run = [], []
    for t, l1, l2 in out:
        res.append([t, l1, l2])
    i = 0
    while i < len(res):
        if res[i][2]:
            j = i
            while j + 1 < len(res) and res[j + 1][2]:
                j += 1
            if res[j][0] - res[i][0] + 2 < 30:
                for k in range(i, j + 1):
                    res[k][2] = False
            i = j + 1
        else:
            i += 1
    return res


# ------------------------------------------------------------------ segments
def build_runs(tag, states, bounds):
    runs = []
    for s in states:
        k = norm_key(tag, s)
        if runs and runs[-1]["key"] == k:
            runs[-1]["t_end"] = s["t_end"]
            runs[-1]["states"].append(s)
        else:
            runs.append({"key": k, "t": s["t"], "t_end": s["t_end"], "states": [s]})
    # frame-accurate starts
    for r in runs[1:]:
        b = bounds.get(f"{r['t']:.1f}")
        r["src_in"] = b["t"] if b else r["t"]
        r["precision"] = "frame (1/25 s)" if b else "2 s grid"
    runs[0]["src_in"], runs[0]["precision"] = 0.0, "file start"
    for i, r in enumerate(runs):
        r["src_out"] = runs[i + 1]["src_in"] if i + 1 < len(runs) else DUR[tag]
    return runs


def split_by_video(runs, min_edge=20.0):
    """Long runs get extra (semantic) cuts where the run's own video-pass segments change topic
    (intra-slide / intra-demo). Slide changes are placed by the frame pass, never here."""
    out = []
    for r in runs:
        cuts = []
        if r["src_out"] - r["src_in"] > 60 and r.get("local_how", "").startswith("content"):
            for v in r["local"][1:]:
                t = v["a"]
                if r["src_in"] + min_edge < t < r["src_out"] - min_edge and all(abs(t - c) > min_edge for c in cuts):
                    cuts.append(t)
        edges = [r["src_in"]] + sorted(cuts) + [r["src_out"]]
        for i in range(len(edges) - 1):
            out.append({**r, "src_in": edges[i], "src_out": edges[i + 1],
                        "split": "visual" if i == 0 else "topic (video pass)",
                        "precision": r["precision"] if i == 0 else "approx (video pass, stretched onto frame run)"})
    return out


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def apply_manual_slides(tag, runs):
    man_prec = "frame (manual: packet-size peak + frame check)"
    for mt, a, b, sn, note in MANUAL_SLIDES:
        if mt != tag:
            continue
        new = []
        for r in runs:
            s, e = r["src_in"], r["src_out"]
            edges = [s] + [x for x in (a, b) if s < x < e] + [e]
            for i in range(len(edges) - 1):
                nr = {**r, "src_in": edges[i], "src_out": edges[i + 1]}
                if edges[i] > s:
                    nr["split"], nr["precision"] = "manual (frame check)", man_prec
                if a - 0.01 <= nr["src_in"] and nr["src_out"] <= b + 0.01:
                    nr["key"], nr["precision"], nr["manual_note"] = ("slide", sn), man_prec, note
                new.append(nr)
        runs = new
    return runs


def build_segments(tag, states, base_runs, vsegs, words, tiles):
    runs = apply_manual_slides(tag, split_by_video(assign_local(base_runs, vsegs)))
    g = STRIP[tag]
    host_tile = px_box(g["x0"], 0, W4K, g["slot_h"])
    cohost_tile = px_box(g["x0"], g["slot_h"], W4K, 2 * g["slot_h"])
    out = []
    for r in runs:
        a, b = r["src_in"], r["src_out"]
        kind, sn = r["key"]
        ov_states = [s for s in states if s["t"] < b and s["t_end"] > a]
        # --- video pass semantics (this run's own, drift-corrected segments)
        ovs = sorted(((overlap(a, b, v["a"], v["b"]), v) for v in r["local"]), key=lambda z: -z[0])
        ovs = [(o, v) for o, v in ovs if o > 0]
        dur = b - a
        main = [v for o, v in ovs if o >= min(0.35 * dur, 20) or o == ovs[0][0]] if ovs else []
        main.sort(key=lambda v: v["a"])
        what = " ".join(dict.fromkeys(v.get("what_happens", "").strip() for v in main if v.get("what_happens")))
        en_w = sum(o for o, v in ovs if isinstance(v.get("energy"), (int, float)))
        energy = (round(sum(o * v["energy"] for o, v in ovs if isinstance(v.get("energy"), (int, float))) / en_w)
                  if en_w else None)
        energy_peak = max((v["energy"] for o, v in ovs if isinstance(v.get("energy"), (int, float))), default=None)
        beats, seen = [], set()
        for o, v in ovs:
            for bt in v.get("beats") or []:
                t = to_sec(bt.get("t"))
                if t is not None and a <= t < b and (round(t), bt.get("note")) not in seen:
                    seen.add((round(t), bt.get("note")))
                    beats.append({"t": round(t, 1), "t_hms": hms(t), "note": bt.get("note")})
        beats.sort(key=lambda z: z["t"])
        v_slide = Counter()
        for o, v in ovs:
            try:
                if v.get("slide_number") not in (None, "", "null"):
                    v_slide[int(v["slide_number"])] += o
            except (TypeError, ValueError):
                pass
        v_sn = v_slide.most_common(1)[0][0] if v_slide else None
        # --- transcript
        ws = [w for w in words if a <= w["start"] < b]
        spk = Counter(w.get("speaker") for w in ws)
        speaker = spk.most_common(1)[0][0] if spk else "никто (нет речи)"
        speech_s = sum(min(w["end"], b) - w["start"] for w in ws)
        # --- tiles
        tl = [x for x in tiles if a - 1 <= x[0] < b]
        host_live = (sum(1 for x in tl if x[1]) / len(tl)) if tl else 0.0
        cohost_live = (sum(1 for x in tl if x[2]) / len(tl)) if tl else 0.0
        faces = [s.get("face_box") for s in ov_states if valid_box(s.get("face_box"))]
        face_med = [statistics.median(f[i] for f in faces) for i in range(4)] if faces else None
        cams = []
        if kind == "camera":
            layout = "speaker_cam_full"
            cams.append({"who": CAM["host"], "tile_box": px_box(0, 0, W4K, H4K), "live_fraction": 1.0,
                         "face_box": box_out(face_med), "face_box_source": "frame pass median"})
        elif kind in ("black", "placeholder"):
            layout = "waiting_screen" if kind == "placeholder" else "other"
        else:
            if host_live > 0.5:
                fb = None
                if face_med:  # keep only if inside the host's tile
                    fx0, fy0 = face_med[1] / 1000 * W4K, face_med[0] / 1000 * H4K
                    if fx0 >= g["x0"] - 20 and fy0 <= g["slot_h"] + 20:
                        fb = box_out(face_med)
                cams.append({"who": CAM["host"], "tile_box": host_tile, "live_fraction": round(host_live, 2),
                             "face_box": fb, "face_box_source": "frame pass median" if fb else None})
            if cohost_live > 0.3:
                cams.append({"who": CAM["cohost"], "tile_box": cohost_tile, "live_fraction": round(cohost_live, 2),
                             "face_box": None, "face_box_source": None})
            if kind == "raffle":
                layout = "drum_raffle"
            else:
                layout = "speaker_cam_small_with_share" if cams else ("slides_share" if kind == "slide" else "demo_screen")
        share_kind = {"slide": "slides", "demo": "demo", "raffle": "demo"}.get(kind, "none")
        content = {"slide": "slide_video" if sn in VIDEO_SLIDES else "slide", "demo": "live_demo",
                   "raffle": "raffle_app", "camera": "camera", "black": "black",
                   "placeholder": "camera_off_placeholder"}[kind]
        spk_short = SPK_SHORT.get(speaker, speaker)
        visible = any(c["who"] == spk_short and c["live_fraction"] > 0.5 for c in cams)
        descs = [s.get("screen_desc") for s in ov_states if s.get("screen_desc")]
        out.append({
            "src_in": round(a, 2), "src_out": round(b, 2), "src_in_hms": hms(a), "src_out_hms": hms(b),
            "dur": round(b - a, 2), "boundary_in": r["split"], "boundary_precision": r["precision"],
            "layout": layout, "screen_content": content, "share_kind": share_kind,
            "slide_number": sn if kind == "slide" else None,
            "slide_title": DECK.get(sn) if kind == "slide" else None,
            "slide_check": (None if kind != "slide" else
                            "manual frame check: " + r["manual_note"] if r.get("manual_note") else
                            "frame pass + video pass agree" if r.get("local_how", "").startswith("content") else
                            f"frame pass only (video pass had {v_sn})"),
            "semantics_source": r.get("local_how"),
            "screen_desc": descs[0] if descs else None,
            "what_happens": what or None,
            "beats": beats,
            "speaker": spk_short,
            "speakers_share": {k: round(v / max(1, len(ws)), 2) for k, v in spk.most_common()},
            "speech_ratio": round(speech_s / max(0.1, b - a), 2),
            "words": len(ws),
            "energy": energy, "energy_peak": energy_peak,
            "speaker_visible": visible,
            "camera_tiles": cams,
        })
    return out


# ------------------------------------------------------------------ highlights
def norm_tokens(s):
    return [w for w in re.sub(r"[^\w\s]", " ", (s or "").lower().replace("ё", "е")).split() if w]


def snap_quote(quote, t_guess, words, win=45.0):
    """Find the quote in the transcript near t_guess; return (start, end, score) or None."""
    q = norm_tokens(re.split(r"\.\.\.|…", quote or "")[0])
    if len(q) < 3:
        return None
    cand = [w for w in words if t_guess - win <= w["start"] <= t_guess + win]
    toks = [norm_tokens(w["word"])[0] if norm_tokens(w["word"]) else "" for w in cand]
    best = None
    n = min(len(q), 8)
    for i in range(len(cand)):
        seg = toks[i:i + n + 2]
        sm = difflib.SequenceMatcher(None, q[:n], seg)
        score = sum(m.size for m in sm.get_matching_blocks()) / n
        if best is None or score > best[0] + 1e-9 or (abs(score - best[0]) < 1e-9 and
                                                      abs(cand[i]["start"] - t_guess) < abs(best[1] - t_guess)):
            best = (score, cand[i]["start"], i)
    if not best or best[0] < 0.6:
        return None
    # end: last quote tokens after the start
    qe = norm_tokens(re.split(r"\.\.\.|…", quote)[-1])[-5:]
    i0 = best[2]
    end = None
    if qe:
        for j in range(i0, min(len(cand), i0 + 120)):
            seg = toks[max(i0, j - len(qe) + 1): j + 1]
            sm = difflib.SequenceMatcher(None, qe, seg)
            if sum(m.size for m in sm.get_matching_blocks()) / len(qe) >= 0.8:
                end = cand[j]["end"]
                break
    return best[1], end, round(best[0], 2)


PICK = [tuple(x) for x in VO.get("pick", [])]  # (source, video-pass t_in) — curated from all video-pass highlights


def build_highlights(hls_all, words_by_tag, segs_by_tag):
    out_all = []
    for h in hls_all:
        tag = h["source"]
        snap = snap_quote(h.get("quote"), h["a"], words_by_tag[tag]) if h.get("quote") else None
        rec = {"source": tag, "t_in": round(h["a"], 1), "t_out": round(h["b"], 1),
               "t_in_hms": hms(h["a"]), "t_out_hms": hms(h["b"]), "type": h.get("type"),
               "description": h.get("description"), "quote": h.get("quote"),
               "video_pass_raw_t_in": round(h["a_raw"], 1),
               "timing": "video-pass range, warped by slide anchors (quote not found in transcript)"}
        best_in, best_out = h["a"], h["b"]
        if snap:
            s, e, sc = snap
            rec["quote_start"] = round(s, 2)
            rec["quote_start_hms"] = hms(s)
            if e and e > s:
                rec["quote_end"] = round(e, 2)
                rec["quote_end_hms"] = hms(e)
            rec["quote_match"] = sc
            rec["timing"] = f"quote located in transcript (token match {sc})"
            if sc >= 0.75 and h["type"] != "drum_spin":
                best_in = s - 1.0
                best_out = max((e or s) + 1.0, s + 6.0)
        fix = HL_FIX.get((tag, round(h["a_raw"])))
        if fix:
            if fix[0] is not None:
                best_in, best_out = fix[0], fix[1]
            rec["timing"] = "manual transcript anchor: " + fix[2]
        rec["best_in"], rec["best_out"] = round(best_in, 1), round(best_out, 1)
        rec["best_in_hms"], rec["best_out_hms"] = hms(best_in), hms(best_out)
        seg = next((x for x in segs_by_tag[tag] if x["src_in"] <= best_in < x["src_out"]), None)
        rec["slide_number"] = seg["slide_number"] if seg else None
        rec["screen_content"] = seg["screen_content"] if seg else None
        out_all.append(rec)
    picks = {(s, round(to_sec(t))) for s, t in PICK}
    sel = [dict(h) for h in out_all if (h["source"], round(h["video_pass_raw_t_in"])) in picks]
    return out_all, sel


# ------------------------------------------------------------------ sensitive
def team_only(text):
    names = [n.strip().lower() for n in re.split(r"[,/;|]", text or "") if n.strip()]
    return bool(names) and all(any(t in n for t in TEAM_NAMES) for n in names)


def build_sensitive(vsens_by_tag):
    items = []
    for tag in TAGS:
        per = defaultdict(list)
        for f in sorted(glob.glob(f"{ROOT}/sens_raw/{tag}_*.json")):
            d = json.load(open(f, encoding="utf-8"))
            tm = {it["k"]: (it["t"], it["file"]) for it in d["items"]}
            for fr in d["result"].get("frames", []):
                try:
                    t, file = tm[int(fr.get("k"))]
                except (KeyError, TypeError, ValueError):
                    continue
                for it in fr.get("items") or []:
                    typ = it.get("type") or "other"
                    text = (it.get("text") or "").strip()
                    sev = it.get("severity") or "medium"
                    if typ == "participant_full_name" and team_only(text):
                        typ, sev = "team_name_label", "none"
                    if typ == "username" and any(h in text.lower() for h in OWNER_HANDLES):
                        typ, sev = "owner_public_handle", "none"
                    per[(typ, bool(it.get("on_slide")))].append(
                        {"t": t, "text": text, "sev": sev, "box": it.get("box") if valid_box(it.get("box")) else None,
                         "file": file})
        for (typ, on_slide), lst in per.items():
            lst.sort(key=lambda z: z["t"])
            iv = []
            for z in lst:
                if iv and z["t"] - iv[-1]["t_last"] <= 6.1:
                    m = iv[-1]
                    m["t_last"] = z["t"]
                    m["texts"][z["text"]] += 1
                    m["sevs"][z["sev"]] += 1
                    if z["box"]:
                        m["boxes"].append(z["box"])
                    m["files"].append(z["file"])
                    m["n"] += 1
                else:
                    iv.append({"t_first": z["t"], "t_last": z["t"], "texts": Counter({z["text"]: 1}),
                               "sevs": Counter({z["sev"]: 1}), "boxes": [z["box"]] if z["box"] else [],
                               "files": [z["file"]], "n": 1})
            for m in iv:
                bx = m["boxes"]
                union = ([min(b[0] for b in bx), min(b[1] for b in bx), max(b[2] for b in bx), max(b[3] for b in bx)]
                         if bx else None)
                sev_order = ["high", "medium", "low", "none"]
                sev = min(m["sevs"], key=lambda s: sev_order.index(s) if s in sev_order else 1)
                a, b = m["t_first"], m["t_last"] + 2.0
                ev = m["files"][:: max(1, len(m["files"]) // 3)][:3]
                items.append({"source": tag, "t_in": round(a, 1), "t_out": round(b, 1), "t_in_hms": hms(a),
                              "t_out_hms": hms(b), "type": typ, "on_slide": on_slide, "severity": sev,
                              "what": [t for t, _ in m["texts"].most_common(6)],
                              "frames_hit": m["n"], "region_box": box_out(union),
                              "found_by": "privacy frame pass (every 2 s)", "evidence_frames": ev})
        # corroborate with the video pass
        for x in vsens_by_tag.get(tag, []):
            hit = [i for i in items if i["source"] == tag and overlap(i["t_in"], i["t_out"], x["a"] - 3, x["b"] + 3) > 0
                   and (i["type"] == x.get("type") or x.get("type") in ("other",))]
            if hit:
                for i in hit:
                    if "video pass" not in i["found_by"]:
                        i["found_by"] += " + video pass"
            else:
                items.append({"source": tag, "t_in": round(x["a"], 1), "t_out": round(x["b"], 1),
                              "t_in_hms": hms(x["a"]), "t_out_hms": hms(x["b"]), "type": x.get("type"),
                              "on_slide": None, "severity": "check", "what": [x.get("description")],
                              "region_hint": x.get("region"), "found_by": "video pass only"})
    return items


ACTIONS = {
    "email": "размыть (вкладка/адрес почты)",
    "client_company": "размыть вкладку с названием клиента",
    "browser_ui": "обрезать/размыть полосу вкладок и адресную строку браузера",
    "username": "размыть @никнеймы (оставить только маски вида P***l)",
    "participant_full_name": "обрезать или размыть колонку плиток Zoom справа (подписи с именем и фамилией)",
    "crm_customer_data": "проверить: если демо-стенд — можно оставить",
    "phone": "проверить: если демо-данные — можно оставить",
    "private_message": "размыть или вырезать",
    "telegram_chat_list": "размыть или вырезать",
    "token_or_key": "вырезать",
    "notification": "размыть или вырезать",
}


def main():
    result = {"meta": {
        "generated_by": "scripts/webinar/vision/build_scenes.py (skill video-editor)",
        "model": "gemini-3.8-flash (google-genai), media_resolution HIGH",
        "method": [
            "video pass: chunks of ~13 min (960x576 @2 fps, source timecode burned into a black strip, mono audio), "
            "thinking HIGH -> segments/beats/highlights/problems/sensitive (raw_v2/)",
            "frame pass: every 2 s from 4K source at 1280x720, deduped to visual states, "
            "classified per state: layout, slide number, camera/face boxes (frames_raw/)",
            "segment boundaries = changes of frame-pass state, refined frame-accurately by decoding the 4K source "
            "around each change at 25 fps (bounds_*.json); long segments additionally split where the video pass "
            "started a new topic segment (boundary_in='topic (video pass)')",
            "speaker/speech_ratio from corrected Deepgram transcript (transcript/part*.words.json)",
            "camera tiles from pixel analysis of the Zoom strip on every 2-s frame (tiles_*.json)",
            "sensitive: focused privacy pass on EVERY 2-s frame (sens_raw/) + video pass corroboration",
        ],
        "time_units": "seconds from start of each source file; *_hms = HH:MM:SS.s",
        "box_convention": "norm_xyxy=[x0,y0,x1,y1] in 0..1 of the 3840x2160 frame; px_4k_xywh in 4K pixels",
        "layout_rule": ("speaker_cam_small_with_share = any screen share with the host's live camera tile in the Zoom strip "
                        "(true for almost the whole webinar); screen_content tells what is shared: slide | slide_video "
                        "(embedded video playing on a slide) | live_demo | raffle_app | camera | black | camera_off_placeholder"),
        "overrides": [{"source": o[0], "from": o[1], "to": o[2], "set": list(o[3]), "why": o[4]} for o in OVERRIDES],
    }, "sources": {}}
    words_by_tag, segs_by_tag, hl_all, pb_all, vs_by_tag = {}, {}, [], [], {}
    warp_stats = {}
    result["meta"]["video_pass_time_warp"] = warp_stats
    for tag in TAGS:
        states = frame_states(tag)
        bounds = json.load(open(f"{ROOT}/bounds_{tag}.json"))
        vsegs, hls, pbs, vsens = load_video_pass(tag)
        words = load_words(tag)
        tiles = load_tiles(tag)
        base_runs = build_runs(tag, states, bounds)
        anchors = compute_warp(vsegs, base_runs)
        apply_warp(anchors, vsegs, hls, pbs, vsens)
        offs = [o for ch in anchors for _, o in anchors[ch]]
        warp_stats[tag] = {"anchors": len(offs),
                           "abs_offset_median_s": round(statistics.median(abs(o) for o in offs), 1) if offs else None,
                           "abs_offset_max_s": round(max(abs(o) for o in offs), 1) if offs else None,
                           "per_chunk": {str(ch): [[round(t, 1), round(o, 1)] for t, o in a] for ch, a in sorted(anchors.items())}}
        segs = build_segments(tag, states, base_runs, vsegs, words, tiles)
        words_by_tag[tag], segs_by_tag[tag], vs_by_tag[tag] = words, segs, vsens
        hl_all += hls
        g = STRIP[tag]
        cohost_iv = []
        for t, l1, l2 in tiles:
            if l2:
                if cohost_iv and t - cohost_iv[-1][1] <= 4.1:
                    cohost_iv[-1][1] = t
                else:
                    cohost_iv.append([t, t])
        result["sources"][tag] = {
            "path": SOURCES[tag], "duration": DUR[tag], "resolution": "3840x2160", "fps": 25,
            "frame_geometry": {
                "zoom_strip_box": px_box(g["x0"], 0, W4K, H4K),
                "host_tile_box": px_box(g["x0"], 0, W4K, g["slot_h"]),
                "cohost_tile_box": px_box(g["x0"], g["slot_h"], W4K, 2 * g["slot_h"]),
                "share_area_without_strip": px_box(0, 0, g["x0"], H4K),
                "note": ("screen share fills the whole 4K frame; the Zoom strip is drawn over its right edge. "
                         "host = slot 1 (live all the time); co-host = slot 2 (live only in the intervals below); "
                         "slots 3+ are camera-off tiles with participant names (sensitive)."),
                "cohost_camera_live": [{"from": round(a, 1), "to": round(b + 2, 1), "from_hms": hms(a), "to_hms": hms(b + 2)}
                                       for a, b in cohost_iv],
            },
            "segments": segs,
        }
        # problems
        for p in pbs:
            pb_all.append({"source": tag, "t_in": round(p["a"], 1), "t_out": round(p["b"], 1), "type": p.get("type"),
                           "description": p.get("description"), "trim_candidate": bool(p.get("trim_candidate")),
                           "found_by": "video pass"})
        sil = json.load(open(f"{ROOT}/silences_{tag}.json", encoding="utf-8"))
        for s in sil.get("-40dB_d3", []):
            seg = next((x for x in segs if x["src_in"] <= s["start"] < x["src_out"]), None)
            ctx = (f"; на экране: {seg['screen_content']}"
                   + (f" слайд {seg['slide_number']} «{seg['slide_title']}»" if seg and seg["slide_number"] else "")
                   ) if seg else ""
            pb_all.append({"source": tag, "t_in": s["start"], "t_out": s["end"], "type": "long_silence",
                           "description": f"Тишина {s['dur']:.1f} с (silencedetect −40 dB){ctx}",
                           "trim_candidate": True, "found_by": "silencedetect"})
        for i, x in enumerate(segs):
            if x["screen_content"] in ("black", "camera_off_placeholder"):
                pb_all.append({"source": tag, "t_in": x["src_in"], "t_out": x["src_out"],
                               "type": "dead_air" if x["screen_content"] == "black" else "waiting_screen",
                               "description": ("чёрный экран при остановке демонстрации" if x["screen_content"] == "black"
                                               else "заглушка Zoom с именем ведущего (камера выключена) после прощания"),
                               "trim_candidate": True, "found_by": "frame pass"})
        # rapid slide flipping (< 4 s per slide, >=2 in a row)
        i = 0
        while i < len(segs):
            j = i
            while j < len(segs) and segs[j]["screen_content"].startswith("slide") and segs[j]["dur"] < 4:
                j += 1
            if j - i >= 2:
                nums = [segs[k]["slide_number"] for k in range(i, j)]
                pb_all.append({"source": tag, "t_in": segs[i]["src_in"], "t_out": segs[j - 1]["src_out"],
                               "type": "fumble", "description": f"быстрое перелистывание слайдов {nums}",
                               "trim_candidate": True, "found_by": "frame pass"})
            i = max(j, i + 1)
    # problems: merge same-type overlaps
    pb_all.sort(key=lambda p: (p["source"], p["t_in"]))
    merged = []
    for p in pb_all:
        m = next((q for q in merged[-4:] if q["source"] == p["source"] and q["type"] == p["type"]
                  and p["t_in"] <= q["t_out"] + 1.5), None)
        if m:
            m["t_out"] = max(m["t_out"], p["t_out"])
            if p["found_by"] not in m["found_by"]:
                m["found_by"] += " + " + p["found_by"]
            if p["description"] not in m["description"]:
                m["description"] += " | " + p["description"]
            m["trim_candidate"] = m["trim_candidate"] or p["trim_candidate"]
        else:
            merged.append(dict(p))
    for p in merged:
        p["t_in_hms"], p["t_out_hms"] = hms(p["t_in"]), hms(p["t_out"])
    hl_all_out, hl_sel = build_highlights(hl_all, words_by_tag, segs_by_tag)
    dq = [(abs(h["quote_start"] - h["video_pass_raw_t_in"]), abs(h["quote_start"] - h["t_in"]))
          for h in hl_all_out if h.get("quote_match", 0) >= 0.75]
    if dq:
        warp_stats["check_vs_transcript_quotes"] = {
            "n": len(dq),
            "median_abs_err_raw_s": round(statistics.median(x for x, _ in dq), 1),
            "median_abs_err_warped_s": round(statistics.median(y for _, y in dq), 1),
            "note": "error = |quote start in transcript − highlight t_in|; t_in may legitimately precede the quote"}
    # individual drum spins, anchored to the transcript words (video-pass beats drift here)
    for etag, a, b, desc, note in EVENTS:
        hl_sel.append({"source": etag, "t_in": a, "t_out": b, "t_in_hms": hms(a), "t_out_hms": hms(b),
                       "type": EVENT_TYPE, "description": desc, "quote": None,
                       "timing": "manual transcript anchor: " + note,
                       "best_in": a, "best_out": b, "best_in_hms": hms(a), "best_out_hms": hms(b),
                       "slide_number": None, "screen_content": EVENT_CONTENT})
    hl_sel.sort(key=lambda h: (h["source"], h["t_in"]))
    sens = build_sensitive(vs_by_tag)
    for tag, lo, hi, types, a, b, sev, on_slide, note in SENS_RESOLVE:
        for s in sens:
            if s["source"] == tag and lo <= s["t_in"] <= hi and s["type"] in types and s["severity"] == "check":
                s.update({"t_in": a, "t_out": b, "t_in_hms": hms(a), "t_out_hms": hms(b), "severity": sev,
                          "on_slide": on_slide, "verified": note})
    for x in SENS_AUDIO:
        sens.append({**x, "t_in_hms": hms(x["t_in"]), "t_out_hms": hms(x["t_out"])})
    for s in sens:
        if s.get("action") and s["type"] == "spoken_full_name":
            continue
        s["action"] = ("не требуется" if s["severity"] in ("none", "low") else ACTIONS.get(s["type"], "проверить"))
    sev_order = {"high": 0, "check": 1, "medium": 2, "low": 3, "none": 4}
    sens.sort(key=lambda s: (sev_order.get(s["severity"], 1), s["source"], s["t_in"]))
    tl = list(TAGS)
    result["continuity"] = {}
    for ta, tb in zip(tl, tl[1:]):
        result["continuity"][f"{ta}_last_slide"] = segs_by_tag[ta][-1]["slide_number"]
        result["continuity"][f"{tb}_first_slide"] = segs_by_tag[tb][0]["slide_number"]
    result["continuity"].update(VO.get("continuity_notes", {}))
    result["continuity"]["skipped_slides"] = sorted(set(DECK) - {x["slide_number"] for t in segs_by_tag for x in segs_by_tag[t]
                                                                 if x["slide_number"]})
    result["highlights"] = hl_sel
    result["highlights_candidates_all"] = hl_all_out
    result["problems"] = merged
    result["sensitive"] = sens
    result["stats"] = {
        **{f"{t}_segments": len(segs_by_tag[t]) for t in TAGS},
        "highlights": len(hl_sel), "highlight_candidates": len(hl_all_out), "problems": len(merged),
        "trim_candidates": sum(1 for p in merged if p["trim_candidate"]),
        "sensitive": len(sens),
        "sensitive_actionable": sum(1 for s in sens if s["severity"] in ("high", "medium", "check")),
    }
    return result


if __name__ == "__main__":
    res = main()
    out = f"{ROOT}/scenes.json"
    tmp = out + ".tmp"
    json.dump(res, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    print(json.dumps(res["stats"], ensure_ascii=False))
