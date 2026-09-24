"""Build final word-level transcripts (json) and readable txt from Deepgram raw + corrections.json.

Inputs : raw/partN.deepgram.json (nova-3, diarize, smart_format), raw/partN.deepgram.plain.json
         (same audio, smart_format/numerals off -> spelled-out numbers), corrections.json
         ({"speaker_names": {part: {dg_id: name}}, "speaker_overrides": [{part, start, end, speaker}],
           "global": [{from, to}], "anchored": [{part, t, from, to, why}]} - an anchored rule that finds nothing is
           REPORTED in anchored_unmatched, never guessed)
Outputs: partN.words.json, partN.txt, corrections_applied.json
Idempotent: always rebuilds from raw.
Job keys: job.json title, transcript.public_surnames (names that may stay in the subtitles: speakers, public
people), transcript.content_rules ([[regex, note]] - editorial flags of the owner, e.g. a product word policy).
usage: python build_outputs.py --job job.json
"""
import json, re, pathlib, datetime

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
BASE = pathlib.Path(J.root) / "transcript"
SRC = {p: J.src(p) for p in J.parts()}
AUDIO = {p: J.p("audio", f"{p}_tr16k.wav") for p in SRC}
CORR = json.loads((BASE / "corrections.json").read_text(encoding="utf-8"))
TITLE = J.get("title", "")

PUNCT = ".,!?;:«»\"'()…—–"
FILLERS = {"ээ", "эээ", "эм", "эмм", "эммм", "мм", "ммм", "хм", "э-э", "а-а"}
NUMWORD = re.compile(r"^(одн|один|перв|два|две|двух|двум|втор|три|трем|трех|трём|трёх|трет|четыр|четв|пят|шест|сем|седьм|восем|восьм|девят|десят|ноль|нол)", re.I)
ORD_SUFFIX = {"ий": "й", "ый": "й", "ой": "й", "ом": "м", "ем": "м", "ое": "е", "ая": "я", "ья": "я",
              "ого": "го", "его": "го", "го": "го", "ые": "е", "ых": "х", "ыми": "ми", "ому": "му", "му": "му",
              "е": "е", "й": "й", "м": "м", "х": "х", "я": "я"}
NBSP = "\u00a0"


def norm(tok: str) -> str:
    t = tok.strip(PUNCT).lower().replace("ё", "е")
    return t


def split_punct(tok: str):
    m = re.match(r"^([" + re.escape(PUNCT) + r"]*)(.*?)([" + re.escape(PUNCT) + r"]*)$", tok, re.S)
    return m.group(1), m.group(2), m.group(3)


def cap_first(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def load(part):
    a = json.loads((BASE / "raw" / f"{part}.deepgram.json").read_text(encoding="utf-8"))
    b = json.loads((BASE / "raw" / f"{part}.deepgram.plain.json").read_text(encoding="utf-8"))
    aw = a["results"]["channels"][0]["alternatives"][0]["words"]
    bw = b["results"]["channels"][0]["alternatives"][0]["words"]
    words = [{"word": w["word"], "punctuated_word": w["punctuated_word"], "start": round(w["start"], 3),
              "end": round(w["end"], 3), "confidence": round(w["confidence"], 4), "dg_speaker": w["speaker"]} for w in aw]
    return a, words, bw


def apply_rule(words, frm, to, part, log, t=None, window=25.0, kind="global"):
    ftoks = [norm(x) for x in frm.split()]
    ttoks = to.split()
    n = len(ftoks)
    i, hits = 0, 0
    while i <= len(words) - n:
        if t is not None and not (t - window <= words[i]["start"] <= t + window):
            i += 1
            continue
        if any(words[i + k].get("corrected") for k in range(n)):
            i += 1
            continue
        if [norm(words[i + k]["punctuated_word"]) for k in range(n)] == ftoks:
            span = words[i:i + n]
            s, e = span[0]["start"], span[-1]["end"]
            if i + n < len(words) and words[i + n]["start"] > s:  # Deepgram spans may overlap the next word
                e = min(e, words[i + n]["start"])
            orig = " ".join(w["punctuated_word"] for w in span)
            new = list(ttoks)
            # keep trailing punctuation of original span unless replacement specifies its own
            _, _, tail = split_punct(span[-1]["punctuated_word"])
            if tail and not new[-1][-1:] in PUNCT:
                new[-1] += tail
            first_orig = split_punct(span[0]["punctuated_word"])[1]
            if first_orig[:1].isupper():
                new[0] = cap_first(new[0])
            weights = [len(x) + 1 for x in new]
            tot, acc = sum(weights), s
            conf = min(w["confidence"] for w in span)
            spk = span[0]["dg_speaker"]
            repl = []
            for k, x in enumerate(new):
                d = (e - s) * weights[k] / tot
                repl.append({"word": norm(x), "punctuated_word": x, "start": round(acc, 3), "end": round(acc + d, 3),
                             "confidence": conf, "dg_speaker": spk, "corrected": True})
                acc += d
            repl[-1]["end"] = round(e, 3)
            repl[0]["orig"] = orig
            words[i:i + n] = repl
            log.append({"part": part, "kind": kind, "t": round(s, 2), "from": orig, "to": " ".join(new)})
            hits += 1
            i += len(repl)
        else:
            i += 1
    return hits


def numerals(words, bw, part, log):
    spelled = formatted = 0
    for i, w in enumerate(words):
        if w.get("corrected"):
            continue
        pre, core, tail = split_punct(w["punctuated_word"])
        m = re.fullmatch(r"(\d+)(?:-([а-яё]+))?", core)
        if not m:
            continue
        n = int(m.group(1))
        suf = m.group(2)
        prev = words[i - 1]["punctuated_word"] if i else "."
        sent_start = prev.rstrip()[-1:] in ".?!…"
        new = None
        if n <= 10:
            ov = [split_punct(y["punctuated_word"])[1] for y in bw
                  if y["end"] > w["start"] + 0.02 and y["start"] < w["end"] - 0.02]
            nums = [x for x in ov if NUMWORD.match(x)]
            if len(nums) == 1:
                new = nums[0].lower()
                if sent_start:
                    new = cap_first(new)
                spelled += 1
        if new is None and suf:
            new = f"{n}-{ORD_SUFFIX.get(suf, suf)}"
            if new != core:
                formatted += 1
        if new is None and not suf and n >= 10000:
            ov = [split_punct(y["punctuated_word"])[1].lower() for y in bw
                  if y["end"] > w["start"] + 0.02 and y["start"] < w["end"] - 0.02]
            if n in (10**6, 10**9) and len(ov) == 1 and re.match(r"^милли(он|ард)", ov[0]):
                new = ov[0]
            elif n % 10**9 == 0:
                new = f"{n // 10**9}{NBSP}млрд"
            elif n % 10**6 == 0:
                new = f"{n // 10**6}{NBSP}млн"
            else:
                new = f"{n:,}".replace(",", NBSP)
            formatted += 1
        if new is not None and new != core:
            log.append({"part": part, "kind": "numeral", "t": round(w["start"], 2), "from": w["punctuated_word"],
                        "to": pre + new + tail})
            w["orig"] = w["punctuated_word"]
            w["punctuated_word"] = pre + new + tail
            w["word"] = norm(new)
    return spelled, formatted


def clean(words):
    for w in words:
        pw = re.sub(r",{2,}", ",", w["punctuated_word"])
        pw = re.sub(r",([.?!])", r"\1", pw)
        w["punctuated_word"] = pw
        if norm(pw) in FILLERS:
            w["filler"] = True


def speakers(words, part):
    names = CORR["speaker_names"][part]
    ovs = [o for o in CORR["speaker_overrides"] if o["part"] == part]
    for w in words:
        w["speaker"] = names.get(str(w["dg_speaker"]), f"Спикер {w['dg_speaker']}")
        for o in ovs:
            if o["start"] <= w["start"] <= o["end"]:
                w["speaker"] = o["speaker"]
                w["speaker_override"] = True


def tighten(words, part):
    """Deepgram stretches a word's end over the following pause (up to ~10 s). Trim such ends to the
    first voiced run after word start (audio energy), bounded by a length-based cap; remove overlaps.
    Original end kept in end_raw."""
    import numpy as np
    import soundfile as sf
    audio, sr = sf.read(AUDIO[part], dtype="int16")  # 16 kHz mono, read once (seeking per word is slow)
    fr = int(0.02 * sr)
    trimmed = 0
    for k, w in enumerate(words):
        nxt = words[k + 1]["start"] if k + 1 < len(words) else None
        end = w["end"]
        if nxt is not None and end > nxt and nxt > w["start"]:
            end = nxt
        L = len(w["word"]) or 1
        cap = min(max(0.6, 0.09 * L + 0.5), 1.6)
        if end - w["start"] > cap:
            a = audio[int(w["start"] * sr):int(end * sr)].astype("float32") / 32768.0
            n = len(a) // fr
            new_end = w["start"] + cap
            if n > 0:
                db = 20 * np.log10(np.sqrt((a[:n * fr].reshape(n, fr) ** 2).mean(1)) + 1e-9)
                voiced = db > -42
                silent_run, first_v = 0, None
                for j, v in enumerate(voiced):
                    if v:
                        first_v = j if first_v is None else first_v
                        silent_run = 0
                    elif first_v is not None:
                        silent_run += 1
                        if silent_run >= 10:  # 200 ms silence closes the word
                            new_end = min(new_end, w["start"] + (j - silent_run + 1) * 0.02 + 0.06)
                            break
            new_end = max(new_end, w["start"] + 0.2)
            end = min(end, new_end)
        if end != w["end"]:
            w["end_raw"] = w["end"]
            w["end"] = round(end, 3)
            trimmed += 1
    return trimmed


def paragraphs(words):
    paras, cur = [], None
    for w in words:
        brk = (cur is None or w["speaker"] != cur["speaker"] or w["start"] - cur["end"] >= 2.5
               or (len(cur["text"]) >= 450 and cur["text"].rstrip()[-1:] in ".?!…") or len(cur["text"]) >= 800)
        if brk:
            if cur:
                paras.append(cur)
            cur = {"start": w["start"], "end": w["end"], "speaker": w["speaker"], "text": w["punctuated_word"]}
        else:
            cur["text"] += " " + w["punctuated_word"]
            cur["end"] = w["end"]
    if cur:
        paras.append(cur)
    for p in paras:
        p["text"] = p["text"][:1].upper() + p["text"][1:]
    return paras


FIRST_NAMES = {"дарья", "дмитрий", "павел", "роман", "илья", "андрей", "константин", "михаил", "макс", "сергей",
               "екатерина", "родион", "виктор", "татьяна", "катя", "дина", "анна", "мария", "ольга", "елена"}
# common first names that trigger the "first name + surname of a private person" flag; extend per job
FIRST_NAMES |= {x.lower() for x in J.get("transcript.first_names", [])}
PUBLIC = {x.lower() for x in J.get("transcript.public_surnames", [])}


def flags(words, part):
    priv, content = [], []
    for i in range(len(words) - 1):
        a, b = norm(words[i]["punctuated_word"]), split_punct(words[i + 1]["punctuated_word"])[1]
        if a in FIRST_NAMES and b[:1].isupper() and re.search(r"(ов|ова|ев|ева|ин|ина|ский|ская|ко|ич)$", b.lower()) \
                and b.lower() not in PUBLIC:
            priv.append({"t": words[i]["start"], "text": f"{words[i]['punctuated_word']} {words[i + 1]['punctuated_word']}",
                         "note": "имя+фамилия частного лица в речи — в субтитрах оставить только имя"})
    rules = [tuple(r) for r in J.get("transcript.content_rules", [])]
    for i, w in enumerate(words):
        t = norm(w["punctuated_word"])
        for rx, note in rules:
            if re.match(rx, t):
                ctx = " ".join(x["punctuated_word"] for x in words[max(0, i - 8):i + 9])
                content.append({"t": w["start"], "speaker": w["speaker"], "word": w["punctuated_word"], "context": ctx, "note": note})
    return priv, content


def mmss(t):
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


def main():
    all_log, summary = [], {}
    for part in J.parts():
        raw, words, bw = load(part)
        log = []
        anch, unmatched = 0, []
        for r in CORR["anchored"]:  # anchored first: global rules must not pre-empt their tokens
            if r["part"] != part:
                continue
            h = apply_rule(words, r["from"], r["to"], part, log, t=r["t"], kind="anchored")
            anch += h
            if h == 0:
                unmatched.append(r)
        g = sum(apply_rule(words, r["from"], r["to"], part, log) for r in CORR["global"])
        sp, fm = numerals(words, bw, part, log)
        clean(words)
        speakers(words, part)
        n_trim = tighten(words, part)
        for k, w in enumerate(words):
            w["i"] = k
        paras = paragraphs(words)
        priv, content = flags(words, part)
        spk_stats = {}
        for w in words:
            s = spk_stats.setdefault(w["speaker"], {"words": 0, "seconds": 0.0, "first": w["start"], "last": w["end"]})
            s["words"] += 1
            s["seconds"] = round(s["seconds"] + (w["end"] - w["start"]), 1)
            s["last"] = w["end"]
        md = raw["metadata"]
        out = {
            "part": part,
            "title": TITLE,
            "source_video": SRC[part],
            "audio_used": AUDIO[part],
            "duration_s": md["duration"],
            "timebase": "seconds from the start of source_video",
            "asr": {"engine": "Deepgram", "model": md["model_info"][md["models"][0]]["name"],
                    "model_version": md["model_info"][md["models"][0]]["version"], "request_id": md["request_id"],
                    "params": "language=ru smart_format punctuate diarize utterances paragraphs numerals keyterm[...]",
                    "second_pass": "same audio, smart_format=false numerals=false — used only to spell small numbers (1->'один'/'одну'...)",
                    "relisten": "unclear spots re-transcribed with gemini-3.8-flash (raw/gemini_relisten.json)",
                    "built_at": datetime.datetime.now().isoformat(timespec="seconds")},
            "schema": {"words[]": "i, word (normalized lowercase), punctuated_word (display), start, end, confidence, "
                                  "speaker (mapped name), dg_speaker (Deepgram id), filler?, corrected?, orig? (text before correction), speaker_override?, "
                                  "end_raw? (Deepgram end before trimming over-stretched/overlapping word ends)",
                       "paragraphs[]": "start, end, speaker, text (same content as the .txt)"},
            "speakers": spk_stats,
            "corrections": {"global_hits": g, "anchored_hits": anch, "numerals_spelled": sp, "numerals_reformatted": fm,
                            "anchored_unmatched": unmatched, "map": "corrections.json", "log": "corrections_applied.json"},
            "privacy_flags": priv,
            "content_flags": content,
            "paragraphs": paras,
            "words": words,
        }
        (BASE / f"{part}.words.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        lines = [f"# {out['title']} — {part.upper()}",
                 f"# Источник: {SRC[part]} (длительность {mmss(md['duration'])})",
                 "# Таймкоды [мм:сс] — от начала этого видеофайла. ASR: Deepgram nova-3 + правки из corrections.json.",
                 ""]
        for p in paras:
            lines.append(f"[{mmss(p['start'])}] {p['speaker']}: {p['text']}")
            lines.append("")
        (BASE / f"{part}.txt").write_text("\n".join(lines), encoding="utf-8")
        all_log += log
        summary[part] = {"words": len(words), "paragraphs": len(paras), "global_hits": g, "anchored_hits": anch,
                         "anchored_unmatched": [u["from"] for u in unmatched], "numerals_spelled": sp,
                         "numerals_reformatted": fm, "word_ends_trimmed": n_trim, "speakers": {k: v["words"] for k, v in spk_stats.items()},
                         "privacy_flags": len(priv), "content_flags": len(content)}
    (BASE / "corrections_applied.json").write_text(json.dumps(all_log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
