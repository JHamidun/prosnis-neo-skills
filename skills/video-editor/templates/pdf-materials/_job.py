"""Job root + config for the PDF material templates (this folder is copied to <job>/materials/pdf_templates).

Resolution order: --job <job.json> in argv, $WEBINAR_JOB, then <this folder>/../../job.json.
JOB = job root (pathlib.Path), CFG = job.json dict. TEMP/TMP go to <job>/tmp (the system drive may be full).
"""
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _find():
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == '--job' and i + 1 < len(argv):
            f = argv[i + 1]
            del argv[i:i + 2]
            return f
        if a.startswith('--job='):
            del argv[i]
            return a.split('=', 1)[1]
    return os.environ.get('WEBINAR_JOB') or str(HERE.parent.parent / 'job.json')


JOB_FILE = pathlib.Path(os.path.expanduser(_find())).resolve()
os.environ['WEBINAR_JOB'] = str(JOB_FILE)  # child scripts (make_all -> build/render) find the same job
CFG = json.loads(JOB_FILE.read_text(encoding='utf-8'))
_root = pathlib.Path(os.path.expanduser(CFG.get('root') or str(JOB_FILE.parent)))
JOB = _root if _root.is_absolute() else (JOB_FILE.parent / _root).resolve()
TMP = JOB / 'tmp'
TMP.mkdir(parents=True, exist_ok=True)
for _k in ('TEMP', 'TMP', 'TMPDIR'):
    os.environ[_k] = str(TMP)


def get(dotted, default=None):
    cur = CFG
    for k in dotted.split('.'):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def rel(p):
    q = pathlib.Path(os.path.expanduser(str(p)))
    return q if q.is_absolute() else JOB / q
