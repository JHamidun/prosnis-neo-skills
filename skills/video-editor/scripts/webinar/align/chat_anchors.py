"""Find moments where the host reads a chat message aloud, to calibrate
C = chat_clock - plaud_clock  (plaud_clock = 17:04:21.800 + plaud_t).
For each chat message: distinctive tokens (>=5 letters, 5-letter stems) searched in the
merged transcript (plaud time) within chat time -75..+15 s (plaud clock assumed ~C early).
Prints D = T_chat - read_time_plaud_clock for matches with >=2 stems (or 1 long rare stem).
Lower bounds of C come from reads (the host reads AFTER the message arrived); an upper bound from a request
("put a +") followed by the first answers. Reference run: C = 24.5 +- 1.0 s -> job.json align.chat_clock_offset_s.
Config: job.json align.t0_wall (recorder device start, local wall clock), align/align_config.json "chat_anchors":
  {"messages": "chat/messages_raw.json" (list or {"all_messages": [...]} of {time_msk "HH:MM:SS", from, text}),
   "pre_words": [{"file": "align/dg_explore_2700_3780.json", "until": 3640}]  (Deepgram of the recorder before part 1),
   "min_letters": 5}
usage: python chat_anchors.py --job job.json -> align/anchors_reads.json"""
import datetime
import json, re
import numpy as np
from offmap import OffMap

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
_t0 = datetime.datetime.fromisoformat(J.need("align.t0_wall"))
P0 = _t0.hour * 3600 + _t0.minute * 60 + _t0.second + _t0.microsecond / 1e6
R = J.root
CFG = J.data("align/align_config.json", {}).get("chat_anchors", {})
MINL = int(CFG.get("min_letters", 5))
STOP = set("""который которые которая только очень можно нужно чтобы потом тоже будет будут этого этот этой
этом всего всех когда где какой какие сейчас просто вообще спасибо здравствуйте привет всем добрый вечер
вечера доброго""".split())


def words_all():
    out = []
    for pw in CFG.get("pre_words", []):
        j = json.load(open(f"{R}/{pw['file']}", encoding="utf-8"))
        for w in j["results"]["channels"][0]["alternatives"][0]["words"]:
            if w["start"] < pw.get("until", 1e9):
                out.append((w["start"], w["word"].lower(), "plaud"))
    for part in J.parts():
        m = OffMap(part)
        j = json.load(open(f"{R}/transcript/raw/{part}.deepgram.json", encoding="utf-8"))
        ws = j["results"]["channels"][0]["alternatives"][0]["words"]
        ts = m.plaud(np.array([w["start"] for w in ws]))
        for w, t in zip(ws, ts):
            out.append((float(t), w["word"].lower(), part))
    out.sort()
    return out


def stems(text):
    toks = re.findall(r"[а-яёa-z]{%d,}" % MINL, text.lower())
    return [t[:5] for t in toks if t not in STOP]


def main():
    W = words_all()
    wt = np.array([w[0] for w in W]); ww = [w[1][:5] for w in W]
    chat = json.load(open(J.rel(CFG.get("messages", "chat/messages_raw.json")), encoding="utf-8"))
    if isinstance(chat, dict):
        chat = chat["all_messages"]
    res = []
    for m in chat:
        h, mi, s = map(int, m["time_msk"].split(":"))
        tc = h * 3600 + mi * 60 + s
        st = list(dict.fromkeys(stems(m["text"])))
        if not st or len(m["text"]) > 160:
            continue
        # plaud_t window where the read may happen (read on plaud clock = tc - C, C in ~[5,45])
        lo, hi = tc - 75 - P0, tc - 0 - P0
        i0, i1 = np.searchsorted(wt, lo), np.searchsorted(wt, hi)
        best = None
        for i in range(i0, i1):
            if ww[i] not in st:
                continue
            # count distinct stems matched within 8 s after i
            j = i; got = set()
            while j < len(W) and wt[j] - wt[i] < 8:
                if ww[j] in st:
                    got.add(ww[j])
                j += 1
            score = len(got) / min(len(st), 4)
            if best is None or len(got) > best[0]:
                best = (len(got), score, wt[i], W[i][2])
        if best and (best[0] >= 2 or (best[0] == 1 and len(st) == 1 and len(st[0]) >= 5 and len(m["text"]) >= 6)):
            D = tc - (P0 + best[2])
            res.append({"chat": m["time_msk"], "from": m["from"][:20], "text": m["text"][:70], "n": best[0],
                        "score": round(best[1], 2), "read_plaud_t": round(best[2], 2), "src": best[3], "D": round(D, 2)})
    for r in res:
        print(f"{r['chat']} D={r['D']:6.2f} n={r['n']} sc={r['score']:.2f} {r['src']:5s} pt={r['read_plaud_t']:8.2f} | {r['from']}: {r['text']}")
    json.dump(res, open(f"{R}/align/anchors_reads.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
