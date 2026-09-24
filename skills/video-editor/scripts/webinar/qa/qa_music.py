"""S12/S13: check a candidate music bed with Gemini (audio): vocals (must be none), whoosh/riser moments (the risers are
put on chapter-card seams: edl_config.json music.cards from_s/step_s), artifacts, mood, bpm, suitability, loop start.
Reference run: own ACE-Step 1.5 bed (skill ace-step), no vocals, 9/10, risers at 15.2 / 31.5 / 47.3 / 63.2 s.

usage: python qa_music.py --job job.json <bed.wav> [out.json]      (default out: style/qa/music_bed.json)
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
PROMPT = ('This is a candidate background music bed for a Russian tech webinar recap (intro, chapter cards, outro; under speech '
          'at -10 dB). Return JSON: {"vocals": bool, "whoosh_or_riser_times_s": [..], "artifacts": "..", "mood": "..", '
          '"bpm_estimate": n, "suitable_1_10": n, "best_loop_start_s": n, "notes": ".."}')


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    from google.genai import types
    c = J.gemini()
    f = c.files.upload(file=sys.argv[1])
    while f.state and f.state.name == 'PROCESSING':
        time.sleep(2)
        f = c.files.get(name=f.name)
    r = c.models.generate_content(model=J.get('qa.model', 'gemini-3.8-flash'), contents=[f, PROMPT],
                                  config=types.GenerateContentConfig(response_mime_type='application/json'))
    out = Path(sys.argv[2] if len(sys.argv) > 2 else J.p('style/qa/music_bed.json'))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text, encoding='utf-8', newline='\n')
    print(r.text)
    json.loads(r.text)  # fail loudly on a non-JSON answer


if __name__ == '__main__':
    main()
