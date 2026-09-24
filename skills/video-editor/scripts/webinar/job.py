"""Job config of the webinar montage pipeline (skill video-editor, references/webinar-montage.md).

One job = one webinar = one folder + one job.json. Every script in scripts/webinar/<stage>/ takes
`--job <path/to/job.json>` (or the env var WEBINAR_JOB) and works inside the job root. The folder
layout under the root is the contract between the stages (the reference webinar was produced in it):

    audio/        16 kHz mono WAVs of every source (<id>_16k.wav; the reference recorder = plaud_16k.wav),
                  cleaned recorder pieces, music/
    proxy/        1080p proxies of the Zoom/stream parts
    align/        coarse/dense offsets, offset maps, junctions, EQ curve   -> timeline.json (root)
    transcript/   Deepgram raw + words/txt per part, corrections.json
    vision/       chunks for Gemini, frames, raw model answers           -> scenes.json
    chat/         parsed chat, stats, reactions
    style/        style.md + tokens.json (single source of numbers for Remotion and the EDL builder)
    edl/          slides, boxes, sketch, edl_config.json                  -> edl.json, chunks/
    remotion/     the Program template (templates/remotion-program), public/, public_lite/, out/bundle*
    render/       rendered chunks, worker logs
    final/        program_mix.wav, the assembled programme
    materials/    PDFs, timemap, texts, cover
    tmp/          TEMP/TMP/TMPDIR of every stage (never the system drive)

Data-contract names kept from the reference run: the reference recorder track is called "plaud"
(audio/plaud_16k.wav, keys plaud_in/plaud_out/plaud_t in timeline.json) whatever device recorded it;
parts are named by their ids in job.json (e.g. part1, part2).

Usage inside a script:
    import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    from job import load
    J = load()            # strips --job <file> from sys.argv, so positional argv parsing keeps working
    ROOT = J.root         # posix string, no trailing slash
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BELOW_NORMAL = 0x00004000
DETACHED = 0x00000008
NEW_GROUP = 0x00000200

SKILLS_DIR = Path(__file__).resolve().parents[3]  # .../skills (video-editor/scripts/webinar/job.py)


def _posix(p) -> str:
    return str(p).replace('\\', '/')


def load_env_file(path) -> int:
    """KEY=VALUE lines into os.environ (existing variables win). Returns the number of keys set."""
    n = 0
    p = Path(os.path.expanduser(str(path)))
    if not p.exists():
        return 0
    for line in p.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        k = k.strip().removeprefix('export ').strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


def low_flags() -> dict:
    """Popen kwargs that start a child at BELOW_NORMAL (Windows) / nice 10 (POSIX)."""
    if os.name == 'nt':
        return {'creationflags': BELOW_NORMAL}
    return {'preexec_fn': lambda: os.nice(10)}


def run_low(cmd, **kw):
    """subprocess.run at low priority: renders, Defender and other sessions share the machine (G-W2)."""
    kw = {**low_flags(), **kw}
    return subprocess.run(cmd, **kw)


def popen_low(cmd, detached=False, **kw):
    fl = low_flags()
    if detached and os.name == 'nt':
        fl['creationflags'] |= DETACHED | NEW_GROUP
    return subprocess.Popen(cmd, **{**fl, **kw})


def lower_self():
    """Drop the priority of the CURRENT python process (heavy numpy / PIL loops)."""
    try:
        if os.name == 'nt':
            import ctypes
            h = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(h, BELOW_NORMAL)
        else:
            os.nice(10)
    except Exception:
        pass


def ffprobe_duration(path) -> float:
    out = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)])
    return float(out.decode().strip())


class Job:
    def __init__(self, file):
        self.file = Path(os.path.expanduser(str(file))).resolve()
        self.cfg: dict = json.loads(self.file.read_text(encoding='utf-8'))
        root = self.cfg.get('root')
        if root:
            r = Path(os.path.expanduser(root))
            if not r.is_absolute():
                r = (self.file.parent / r).resolve()
        else:
            r = self.file.parent
        self.root_path = r
        self.root = _posix(r)
        self.tmp = f'{self.root}/tmp'
        self.fps = int(self.cfg.get('fps', 25))

    # ---- config access
    def get(self, dotted: str, default=None):
        cur = self.cfg
        for k in dotted.split('.'):
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur

    def need(self, dotted: str):
        v = self.get(dotted)
        if v is None:
            raise SystemExit(f'job.json: missing required key "{dotted}" ({self.file})')
        return v

    def p(self, *parts) -> str:
        """Path under the job root (posix string)."""
        return _posix(Path(self.root, *parts))

    def rel(self, path) -> str:
        """A path from job.json: absolute stays, relative is taken from the job root."""
        q = Path(os.path.expanduser(str(path)))
        return _posix(q if q.is_absolute() else Path(self.root, q))

    def data(self, rel: str, default=None):
        """JSON data file of the job (edl/edl_config.json, vision/vision_overrides.json, ...)."""
        q = Path(self.p(rel))
        if not q.exists():
            if default is not None:
                return default
            raise SystemExit(f'missing job data file {q}')
        return json.loads(q.read_text(encoding='utf-8'))

    # ---- sources
    @property
    def sources(self) -> list:
        return self.cfg.get('sources', [])

    def source(self, sid: str) -> dict:
        for s in self.sources:
            if s['id'] == sid:
                return s
        raise SystemExit(f'job.json: no source with id "{sid}"')

    def src(self, sid: str) -> str:
        return self.rel(self.source(sid)['path'])

    def parts(self) -> list:
        """ids of the parts that are aligned to the reference (align.parts or all non-recorder sources)."""
        ps = self.get('align.parts')
        if ps:
            return list(ps)
        return [s['id'] for s in self.sources if s.get('kind') != 'recorder']

    def vision_tags(self) -> dict:
        """{tag: source id} for the vision/stories stages: sources[].tag or P1..Pn in the order of parts()."""
        out = {}
        for i, sid in enumerate(self.parts(), 1):
            out[self.source(sid).get('tag') or f'P{i}'] = sid
        return out

    def ref_id(self) -> str:
        return self.get('align.reference') or next((s['id'] for s in self.sources if s.get('kind') == 'recorder'), 'recorder')

    def dur(self, sid: str) -> float:
        """Source duration: job.json sources[].duration, else ffprobe (cached in tmp/durations.json)."""
        s = self.source(sid)
        if s.get('duration'):
            return float(s['duration'])
        cache = Path(self.tmp, 'durations.json')
        c = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
        key = self.src(sid)
        if key not in c:
            c[key] = ffprobe_duration(key)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
        return float(c[key])

    # ---- environment
    def setup_env(self):
        """TEMP/TMP/TMPDIR on the job drive (the system drive may be full; Defender scans it)."""
        Path(self.tmp).mkdir(parents=True, exist_ok=True)
        for k in ('TEMP', 'TMP', 'TMPDIR'):
            os.environ[k] = self.tmp
        cache = self.get('npm_cache')
        if cache:
            os.environ['npm_config_cache'] = self.rel(cache)
        return os.environ

    def env(self) -> dict:
        """A copy of os.environ with TEMP on the job drive - pass as env= to subprocesses."""
        self.setup_env()
        return dict(os.environ)

    def load_env(self) -> int:
        """API keys: job.json env_file, then $WEBINAR_ENV_FILE. Keys stay env-only (never in code)."""
        n = 0
        for f in (self.cfg.get('env_file'), os.environ.get('WEBINAR_ENV_FILE')):
            if f:
                n += load_env_file(f)
        return n

    def key(self, name: str) -> str:
        self.load_env()
        v = os.environ.get(name)
        if not v:
            raise SystemExit(f'env var {name} is not set (job.json env_file / WEBINAR_ENV_FILE / environment)')
        return v

    def gemini(self):
        """google-genai client with GOOGLE_API_KEY (GEMINI_API_KEY is popped: it conflicts in the SDK)."""
        k = self.key('GOOGLE_API_KEY')
        os.environ.pop('GEMINI_API_KEY', None)
        from google import genai  # noqa: E402
        return genai.Client(api_key=k)

    def skill(self, name: str) -> str:
        """Path of a sibling skill (sketch-course-video, manus-slides ...)."""
        env = os.environ.get(name.upper().replace('-', '_') + '_DIR')
        return _posix(env or (SKILLS_DIR / name))


_LOADED: Job | None = None


def load(argv: list | None = None) -> Job:
    """Find --job <file> (or --job=<file>) in argv / $WEBINAR_JOB, strip it from sys.argv, set TEMP.
    The resolved file is exported as WEBINAR_JOB, so modules imported by a script (offmap, dense,
    build_outputs ...) load the same job; repeated calls return the same Job."""
    global _LOADED
    argv = sys.argv if argv is None else argv
    file = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--job' and i + 1 < len(argv):
            file = argv[i + 1]
            del argv[i:i + 2]
            continue
        if a.startswith('--job='):
            file = a.split('=', 1)[1]
            del argv[i]
            continue
        i += 1
    file = file or os.environ.get('WEBINAR_JOB')
    if not file:
        raise SystemExit('pass --job <job.json> or set WEBINAR_JOB (see templates/job.example.json)')
    resolved = str(Path(os.path.expanduser(file)).resolve())
    if _LOADED is not None and str(_LOADED.file) == resolved:
        return _LOADED
    os.environ['WEBINAR_JOB'] = resolved
    j = Job(resolved)
    j.setup_env()
    _LOADED = j
    return j


if __name__ == '__main__':
    J = load()
    print(json.dumps({'root': J.root, 'fps': J.fps, 'reference': J.ref_id(), 'parts': J.parts(),
                      'sources': {s['id']: J.src(s['id']) for s in J.sources}}, ensure_ascii=False, indent=1))
