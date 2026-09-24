"""Build word-level transcript of the Plaud-only pieces (intro before PART1, gap between parts).

Input : transcript/raw/<piece>.deepgram{,.plain}.json (Deepgram nova-3 ru on the CLEANED pieces,
        align/dg_pieces.py), transcript/corrections.json (global rules shared with part1/part2),
        transcript/recorder_corrections.json (piece-specific rules, each with its evidence:
        {"title", "speaker", "rules": {piece: [[t, from, to, evidence]]}, "inserts": {piece: [[after_t, [[word, s, e]], ev]]},
         "fix_times": [[piece, t_start_now, word, start, end]], "flag_extra": {piece: [{t_from, t_to, note}]}}),
        transcript/raw/gemini_relisten_plaud.json (evidence). Pieces = align/align_config.json "pieces".
Output: transcript/plaud_intro.words.json (+ plaud_intro.txt). Same schema as partN.words.json;
        top level = intro piece, key "gap" = gap piece. Idempotent: rebuilds from raw.
Reuses the part pipeline (transcript/build_outputs.py): apply_rule, numerals, clean, tighten, paragraphs, flags.
"""
import datetime
import json
import pathlib
import sys

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "transcript"))
import build_outputs as bo  # noqa: E402

R = pathlib.Path(J.root)
RC = J.data("transcript/recorder_corrections.json", {})
C_SEC = float(J.get("align.chat_clock_offset_s", 0.0))   # wall = recorder device clock + C (align/chat_anchors.py)
C_ERR = float(J.get("align.chat_clock_err_s", 1.0))
PLAUD_T0 = datetime.datetime.fromisoformat(J.need("align.t0_wall"))  # recorder start_time (device clock)
WALL0 = PLAUD_T0 + datetime.timedelta(seconds=C_SEC)            # wall clock of plaud_t = 0
PIECES = {k: {"plaud_in": v[0], "plaud_out": v[1], "wav": f"audio/{k}.wav"}
          for k, v in J.data("align/align_config.json", {}).get("pieces", {}).items()}
# piece-specific corrections: (t in piece seconds, from, to, evidence)
RULES = {k: [tuple(r) for r in v] for k, v in RC.get("rules", {}).items()}
INSERTS = {k: [(a, [tuple(x) for x in ins], ev) for (a, ins, ev) in v] for k, v in RC.get("inserts", {}).items()}
FIX_TIMES = {(p, t, w): (s, e) for (p, t, w, s, e) in RC.get("fix_times", [])}
FLAG_EXTRA = RC.get("flag_extra", {})
SPEAKER = RC.get("speaker") or J.get("speakers.host.name", "Ведущий")
TITLE = RC.get("title") or J.get("title", "")


def wall(plaud_t):
    return (WALL0 + datetime.timedelta(seconds=plaud_t)).strftime("%H:%M:%S.%f")[:-4]


def build(piece):
    P = PIECES[piece]
    a = json.loads((R / "transcript/raw" / f"{piece}.deepgram.json").read_text(encoding="utf-8"))
    b = json.loads((R / "transcript/raw" / f"{piece}.deepgram.plain.json").read_text(encoding="utf-8"))
    aw = a["results"]["channels"][0]["alternatives"][0]["words"]
    bw = b["results"]["channels"][0]["alternatives"][0]["words"]
    words = [{"word": w["word"], "punctuated_word": w["punctuated_word"], "start": round(w["start"], 3),
              "end": round(w["end"], 3), "confidence": round(w["confidence"], 4), "dg_speaker": w["speaker"]} for w in aw]
    log, unmatched = [], []
    for (t, frm, to, ev) in RULES.get(piece, []):
        n0 = len(log)
        h = bo.apply_rule(words, frm, to, piece, log, t=t, window=25.0, kind="anchored")
        for e in log[n0:]:
            e["evidence"] = ev
        if h == 0:
            unmatched.append({"t": t, "from": frm, "to": to})
    for (key, se) in FIX_TIMES.items():
        if key[0] != piece:
            continue
        for w in words:
            if abs(w["start"] - key[1]) < 0.05 and w["punctuated_word"] == key[2]:
                w["orig_times"] = [w["start"], w["end"]]
                w["start"], w["end"] = se
                w["corrected"] = True
    for (after_t, ins, ev) in INSERTS.get(piece, []):
        k = next(i for i, w in enumerate(words) if w["start"] > after_t)
        new = [{"word": bo.norm(x), "punctuated_word": x, "start": s, "end": e, "confidence": 0.0,
                "dg_speaker": words[k]["dg_speaker"], "corrected": True, "inserted": True} for (x, s, e) in ins]
        words[k:k] = new
        log.append({"part": piece, "kind": "inserted", "t": ins[0][1], "from": "", "to": " ".join(x[0] for x in ins), "evidence": ev})
    g = sum(bo.apply_rule(words, r["from"], r["to"], piece, log) for r in bo.CORR["global"])
    sp, fm = bo.numerals(words, bw, piece, log)
    bo.clean(words)
    for w in words:  # diarization: one voice in the pieces = host (recorder on his desk); verify by reading
        w["speaker"] = SPEAKER
    bo.AUDIO[piece] = str(R / "audio" / f"{piece}_16k.wav")
    n_trim = bo.tighten(words, piece)
    for k, w in enumerate(words):
        w["i"] = k
        w["plaud_t"] = round(w["start"] + P["plaud_in"], 3)
    paras = bo.paragraphs(words)
    for p in paras:
        p["plaud_t"] = round(p["start"] + P["plaud_in"], 3)
        p["wall_msk"] = wall(p["plaud_t"])
    priv, content = bo.flags(words, piece)
    md = a["metadata"]
    dur = round(P["plaud_out"] - P["plaud_in"], 3)
    return {
        "piece": piece,
        "title": TITLE,
        "source_audio": str(R / P["wav"]).replace("\\", "/"),
        "source_plaud": {"file": J.src(J.ref_id()), "plaud_file_id": J.source(J.ref_id()).get("file_id"),
                         "plaud_in": P["plaud_in"], "plaud_out": P["plaud_out"]},
        "duration_s": dur,
        "timebase": f"start/end = seconds from the start of {P['wav']}; plaud_t = start + {P['plaud_in']}; "
                    f"wall_msk = {WALL0.strftime('%H:%M:%S.%f')[:-5]} + plaud_t (C={C_SEC}±{C_ERR} s)",
        "asr": {"engine": "Deepgram", "model": md["model_info"][md["models"][0]]["name"],
                "model_version": md["model_info"][md["models"][0]]["version"], "request_id": md["request_id"],
                "params": "language=ru punctuate diarize utterances paragraphs smart_format numerals keyterm[...] (on the cleaned piece)",
                "second_pass": "same audio, smart_format=false numerals=false — used only to spell small numbers",
                "relisten": "disputed spots re-listened with gemini-3.8-flash (transcript/raw/gemini_relisten_plaud.json)",
                "built_at": datetime.datetime.now().isoformat(timespec="seconds"), "builder": "align/build_plaud_words.py"},
        "schema": {"words[]": "i, word, punctuated_word, start, end, confidence, speaker, dg_speaker, plaud_t, filler?, "
                              "corrected?, orig?, inserted? (word Deepgram dropped, restored from evidence; confidence 0), end_raw?",
                   "paragraphs[]": "start, end, speaker, text, plaud_t, wall_msk"},
        "corrections": {"anchored_hits": sum(1 for e in log if e["kind"] == "anchored"), "anchored_unmatched": unmatched,
                        "global_hits": g, "numerals_spelled": sp, "numerals_reformatted": fm, "word_ends_trimmed": n_trim,
                        "log": log},
        "privacy_flags": priv,
        "content_flags": content,
        "segment_notes": FLAG_EXTRA.get(piece, []),
        "paragraphs": paras,
        "words": words,
    }


def main():
    # contract: the FIRST piece is the top level of plaud_intro.words.json, every other piece sits under its
    # name without "_plaud" (reference run: intro_plaud = top level, gap_plaud -> key "gap")
    names = list(PIECES)
    built = [build(n) for n in names]
    out = dict(built[0])
    for n, b in zip(names[1:], built[1:]):
        out[n.replace("_plaud", "")] = b
    (R / "transcript" / "plaud_intro.words.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# {TITLE} — звук диктофона: куски, которых нет в записи Zoom",
             "# [мм:сс] — от начала куска; в скобках — время по Москве (±1 с). ASR: Deepgram nova-3 + правки (см. .words.json)", ""]
    for n, b in zip(names, built):
        P = PIECES[n]
        lines += [f"## {n}.wav (plaud {P['plaud_in']:.2f}–{P['plaud_out']:.2f})", ""]
        for p in b["paragraphs"]:
            lines += [f"[{bo.mmss(p['start'])}] ({p['wall_msk'][:8]}) {p['speaker']}: {p['text']}", ""]
    (R / "transcript" / "plaud_intro.txt").write_text("\n".join(lines), encoding="utf-8")
    for x in built:
        c = x["corrections"]
        print(x["piece"], "words", len(x["words"]), "paras", len(x["paragraphs"]), "anchored", c["anchored_hits"],
              "unmatched", c["anchored_unmatched"], "global", c["global_hits"], "num", c["numerals_spelled"], c["numerals_reformatted"],
              "trim", c["word_ends_trimmed"], "priv", len(x["privacy_flags"]), "content", len(x["content_flags"]))


if __name__ == "__main__":
    main()
