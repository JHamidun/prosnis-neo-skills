"""S13: chunk-by-chunk Gemini frame QA while the render runs: every encoded chunk with a valid sidecar
(render/enc/chunk_NNN.mp4 + .src.json, encode_chunks.py) -> render/enc/qa/chunk_NNN.json (qa_frames.qa, a frame every
15 s). Re-runs when the encode changes (the signature is stored in the json; stale frame jpgs are deleted).
Summary lines -> render/enc/qa/summary.jsonl. Exits when every chunk is QA'd.
A defect found here costs one chunk re-render instead of a whole programme (reference run: a chunk rendered under
memory pressure showed an uncropped browser tab strip with a mailbox name - withdrawn and re-rendered).

usage: python qa_watch.py --job job.json [--step 15]
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
import qa_frames  # noqa: E402

ENC = Path(J.p('render/enc'))
QA = ENC / 'qa'
QA.mkdir(parents=True, exist_ok=True)
IDX = json.load(open(J.p('edl/chunks/index.json'), encoding='utf-8'))
SUMMARY = QA / 'summary.jsonl'
STEP = float(sys.argv[sys.argv.index('--step') + 1]) if '--step' in sys.argv else 15.0

while True:
    done = 0
    for c in IDX['chunks']:
        name = c['id'].replace('full_', 'chunk_')
        enc, side, out = ENC / f'{name}.mp4', ENC / f'{name}.src.json', QA / f'{name}.json'
        if not enc.exists() or not side.exists():
            continue
        sig = {'enc_size': enc.stat().st_size, 'enc_mtime': enc.stat().st_mtime}
        if out.exists():
            try:
                if json.loads(out.read_text(encoding='utf-8')).get('sig') == sig:
                    done += 1
                    continue
            except Exception:  # noqa: BLE001
                pass
            out.unlink()
        for jpg in (QA / name).glob('*.jpg'):
            jpg.unlink()
        data = qa_frames.qa(enc, STEP)
        data['sig'] = sig
        with open(out, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        with open(SUMMARY, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps({'id': name, 'at': time.strftime('%H:%M:%S'), 'ok': data.get('ok'), 'score': data.get('score_1_10'),
                                'issues': [(i.get('frame'), i.get('severity'), i.get('what')) for i in data.get('issues', [])]},
                               ensure_ascii=False) + '\n')
        done += 1
    if done == len(IDX['chunks']):
        print('ALL QA DONE', flush=True)
        break
    time.sleep(60)
