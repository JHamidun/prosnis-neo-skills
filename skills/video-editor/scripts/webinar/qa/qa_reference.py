"""S13: Gemini video QA of an excerpt AGAINST the owner's reference video (the quality bar is set by a video, not by
words). Uploads the reference + the rendered excerpt (with audio), asks for a strict timestamped critique: premium
score, score vs reference, issues, text/UI covered by overlays, word sync, motion, readability, privacy.

NOISY by design (G-Q1): the model samples ~1 frame/s, so it reports eased 22-30 f moves as "hard cuts", hears a
"whoosh" that does not exist, and scores the same file 8 -> 6 -> 7. Accept only what a frame check confirms
(contact_sheet.py); never use the score as a metric; compare variants pairwise in BOTH orders (G-Q2).

job.json: qa.reference (path of the reference video), qa.model
usage: python qa_reference.py --job job.json <round> <excerpt.mp4> "<intent: what this excerpt should show>"
       -> <excerpt dir>/qa/<excerpt>.<round>.json (skip-if-done)
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
MODEL = J.get('qa.model', J.get('vision.model', 'gemini-3.8-flash'))

PROMPT = """You are a demanding senior motion designer reviewing a montage for a paying client.
Video 1 is the client's favourite REFERENCE (quality bar). Video 2 is our EXCERPT: {intent}
Audio is Russian speech. Judge Video 2 against the reference and against broadcast polish.

Return JSON only:
{{"score_premium_1_10": n, "score_vs_reference_1_10": n,
  "strengths": [".."],
  "issues": [{{"t": "mm:ss", "severity": "high|medium|low", "what": "..", "fix": ".."}}],
  "covered_text_or_ui": [{{"t": "mm:ss", "what": "which overlay covers which slide text / UI"}}],
  "sync": "are drawings/highlights/pills in sync with the spoken words? cite times",
  "motion": "morphs, springs, punch-ins: smooth or janky? cite times",
  "readability": "captions, chat, poll legibility",
  "privacy": "any e-mails, phone numbers, full names of private people, tokens visible? cite times"}}
Be specific with timestamps of Video 2. Do not praise generically."""


def upload(client, p):
    f = client.files.upload(file=str(p))
    while f.state and f.state.name == 'PROCESSING':
        time.sleep(3)
        f = client.files.get(name=f.name)
    return f


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    rnd, excerpt, intent = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out = excerpt.parent / 'qa' / f'{excerpt.stem}.{rnd}.json'
    if out.exists() and out.stat().st_size > 100:
        print('cached', out)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    from google.genai import types
    client = J.gemini()
    ref = upload(client, J.rel(J.need('qa.reference')))
    ex = upload(client, excerpt)
    r = client.models.generate_content(
        model=MODEL, contents=[ref, ex, PROMPT.format(intent=intent)],
        config=types.GenerateContentConfig(response_mime_type='application/json', media_resolution='MEDIA_RESOLUTION_HIGH',
                                           thinking_config=types.ThinkingConfig(thinking_level='high')))
    try:
        data = json.loads(r.text)
    except Exception:  # noqa: BLE001
        data = {'raw': r.text}
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print('OK', out, data.get('score_premium_1_10'), data.get('score_vs_reference_1_10'))


if __name__ == '__main__':
    main()
