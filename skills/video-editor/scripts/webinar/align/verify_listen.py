"""'Listening points': independent check of the offset map using two DIFFERENT ASR runs.
For each verify window, Plaud words (Deepgram on the Plaud slice) are matched to the part's words
(Deepgram on the Zoom audio, mapped to Plaud time through OffMap). Good alignment => high match
rate and |median dt| ~ 0.0x s. Output: align/verify_listen.json
Windows: align/align_config.json -> "verify_windows": {slice name in dg_slices: part}; the Plaud-side slices come
from dg_slices.py (6 windows spread over the speech: start / middle / end of every part in the reference run)."""
import json, re
import numpy as np
from offmap import OffMap

import os as _os, sys as _sys  # job config (scripts/webinar/job.py)
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
from job import load as _load_job  # noqa: E402
J = _load_job()
R = J.root
WIN = J.data("align/align_config.json", {}).get("verify_windows") or {
    "v_p1_030": "part1", "v_p1_1200": "part1", "v_p1_2330": "part1",
    "v_p2_030": "part2", "v_p2_2400": "part2", "v_p2_4660": "part2"}


def norm(w):
    return re.sub(r"[^а-яёa-z0-9]", "", w.lower()).replace("ё", "е")


def part_words(part):
    j = json.load(open(f"{R}/transcript/raw/{part}.deepgram.json", encoding="utf-8"))
    ws = j["results"]["channels"][0]["alternatives"][0]["words"]
    m = OffMap(part)
    st = np.array([w["start"] for w in ws])
    return [(float(pt), norm(w["word"]), float(t)) for w, pt, t in zip(ws, m.plaud(st), st)]


def main():
    cache = {p: part_words(p) for p in sorted(set(WIN.values()))}
    res = {}
    for name, part in WIN.items():
        j = json.load(open(f"{R}/align/dg_plaud/{name}.json", encoding="utf-8"))
        a, b = j["slice"]["start_s"], j["slice"]["end_s"]
        pw = [(w["start"], norm(w["word"])) for w in j["results"]["channels"][0]["alternatives"][0]["words"]]
        zw = [x for x in cache[part] if a - 2 <= x[0] <= b + 2]
        used = set(); dts = []; part_t = []
        for t, w in pw:
            if len(w) < 3:
                continue
            best = None
            for k, (zt, zwd, zsrc) in enumerate(zw):
                if k in used or zwd != w or abs(zt - t) > 1.0:
                    continue
                if best is None or abs(zt - t) < abs(zw[best][0] - t):
                    best = k
            if best is not None:
                used.add(best); dts.append(zw[best][0] - t); part_t.append(zw[best][2])
        n_elig = sum(1 for _, w in pw if len(w) >= 3)
        d = np.array(dts) if dts else np.array([np.nan])
        res[name] = {"part": part, "plaud_window": [a, b],
                     "part_window": [round(min(part_t), 2), round(max(part_t), 2)] if part_t else None,
                     "plaud_words_eligible": n_elig, "matched": len(dts),
                     "match_rate": round(len(dts) / max(1, n_elig), 3),
                     "median_dt_s": round(float(np.median(d)), 3),
                     "mad_dt_s": round(float(np.median(np.abs(d - np.median(d)))), 3),
                     "p90_abs_dt_s": round(float(np.percentile(np.abs(d), 90)), 3)}
        print(name, res[name])
    json.dump(res, open(f"{R}/align/verify_listen.json", "w"), indent=1)


if __name__ == "__main__":
    main()
