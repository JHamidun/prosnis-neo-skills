"""S13: cut test excerpts out of edl/edl.json with the SAME re-basing as the render chunks (split_chunks.chunk), so a
test renders exactly what the full render will show at those frames (intro, a poll, chapter card + video, the raffle,
the outro ...). Render them with templates/remotion-program/render_program.mjs and look at every new element.

Tests: edl_config.json "tests" {"test_intro": [0, 700], "test_outro": [184350, "end"]} or CLI name:from:to pairs.
usage: python make_tests.py --job job.json [name:from:to ...]   -> test/edl_<name>.json
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load  # noqa: E402

J = load()
import split_chunks as S  # noqa: E402

S.load()
tests = {}
for a in sys.argv[1:]:
    name, c0, c1 = a.split(':')
    tests[name] = [int(c0), c1]
if not tests:
    tests = J.data('edl/edl_config.json', {}).get('tests', {})
if not tests:
    raise SystemExit('no tests: pass name:from:to or add "tests" to edl/edl_config.json')
out = Path(J.p('test'))
out.mkdir(parents=True, exist_ok=True)
for k, (name, (c0, c1)) in enumerate(tests.items()):
    c1 = S.E['durationInFrames'] if c1 in ('end', None) else int(c1)
    e = S.chunk(900 + k, int(c0), c1)
    e['id'] = name
    S.save(out / f'edl_{name}.json', e)
    print(name, c0, c1, c1 - int(c0), 'feeds', len(e['feeds']), 'chat', len(e['chat']), 'polls', len(e['polls']), 'winners', len(e['winners']))
