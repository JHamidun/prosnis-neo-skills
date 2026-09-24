"""Upload the deck videos to Yandex Disk, publish them and checkpoint the public links into video_links.json
(skip-if-done by md5: a file already on the Disk with the same md5 and size is not uploaded again).

plan.json - one entry per video on a slide: [{"slide": 12, "file": "<original video>.mp4", "rect": [x, y, w, h],
             "title": "<slide title>"}]. Build it from pptx_video_rects.py output + your deck's video map, e.g. with
             `plan` below for a manus-slides exec-sketch deck (assemble/assets_map.json + deck.merged.json; the pptx shape
             name is "video <file stem>").
Remote name: "Слайд NN — <title>[ (i из n)].mp4" in the folder given by --folder; the folder is published too.
Token: YANDEX_OAUTH_TOKEN from the environment (never in code). 5 uploads in parallel, 3 retries each, md5 re-checked.

usage:
  python upload_videos_yadisk.py plan <pptx_videos.json> <assets_map.json> <deck.merged.json> <plan.json>
  python upload_videos_yadisk.py upload <plan.json> <video_links.json> --folder "/<папка на Диске>"
"""
import hashlib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API = 'https://cloud-api.yandex.net/v1/disk'


def clean(t):
    t = re.sub(r'[\\/:*?"<>|]', '', t)
    return re.sub(r'\s+', ' ', t).strip().rstrip('.')


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def make_plan(pv_p, am_p, deck_p, out_p):
    pv = json.load(open(pv_p, encoding='utf-8'))
    am = json.load(open(am_p, encoding='utf-8'))
    deck = json.load(open(deck_p, encoding='utf-8'))
    titles = {s['id']: s.get('title', '') for s in deck['slides']}
    src = {}
    for sid, e in am['slides'].items():
        for ins in e.get('inserts', []):
            if ins.get('type') == 'video':
                src[Path(ins['path']).stem] = (sid, ins['path'])
    plan = []
    for v in pv['videos']:
        stem = v['shape'].replace('video ', '').strip()
        if stem not in src:
            raise SystemExit(f'pptx video shape {v["shape"]!r} (slide {v["page"]}) has no file in {am_p}')
        sid, path = src[stem]
        plan.append({'slide': v['page'], 'slide_id': sid, 'file': path, 'rect': v['rect'], 'title': titles.get(sid, ''), 'size': v.get('size')})
    Path(out_p).write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    print('plan', len(plan), '->', out_p)


def upload(plan_p, out_p, folder):
    import requests
    H = {'Authorization': f"OAuth {os.environ['YANDEX_OAUTH_TOKEN']}"}
    plan = json.load(open(plan_p, encoding='utf-8'))
    OUT = Path(out_p)

    def meta(path):
        r = requests.get(f'{API}/resources', headers=H, params={'path': path, 'fields': 'name,size,md5,public_url,public_key'}, timeout=60)
        return r.status_code, (r.json() if r.content else {})

    done = {e['file']: e for e in json.load(open(OUT, encoding='utf-8'))} if OUT.exists() else {}
    code, _ = meta(folder)
    if code == 404:
        print('mkdir', requests.put(f'{API}/resources', headers=H, params={'path': folder}, timeout=60).status_code)
    per_page = {}
    for v in plan:
        per_page.setdefault(v['slide'], []).append(v)
    results = []
    lock = threading.Lock()

    def checkpoint():
        merged = dict(done)
        for e in results:
            merged[e['file']] = e
        OUT.write_text(json.dumps(sorted(merged.values(), key=lambda e: (e['slide'], e['disk_path'])), ensure_ascii=False, indent=1),
                       encoding='utf-8', newline='\n')

    def job(v):
        siblings = per_page[v['slide']]
        idx = siblings.index(v) + 1
        suffix = f' ({idx} из {len(siblings)})' if len(siblings) > 1 else ''
        rname = f"Слайд {v['slide']:02d} — {clean(v.get('title') or Path(v['file']).stem)}{suffix}.mp4"
        rpath = f'{folder}/{rname}'
        lmd5, lsize = md5(v['file']), os.path.getsize(v['file'])
        code, j = meta(rpath)
        if not (code == 200 and j.get('md5') == lmd5 and j.get('size') == lsize):
            for attempt in range(3):
                try:
                    r = requests.get(f'{API}/resources/upload', headers=H, params={'path': rpath, 'overwrite': 'true'}, timeout=60)
                    r.raise_for_status()
                    t0 = time.time()
                    with open(v['file'], 'rb') as f:
                        u = requests.put(r.json()['href'], data=f, timeout=3600)
                    print(f'upload {u.status_code} {rname} {lsize / 1e6:.1f}MB {time.time() - t0:.0f}s')
                    break
                except Exception as ex:  # noqa: BLE001
                    print('  retry', attempt, rname, repr(ex)[:200])
                    time.sleep(5)
            for _ in range(60):
                code, j = meta(rpath)
                if code == 200 and j.get('md5') == lmd5:
                    break
                time.sleep(2)
        else:
            print('skip (already uploaded, md5 match)', rname)
        if not j.get('public_url'):
            print('  publish', requests.put(f'{API}/resources/publish', headers=H, params={'path': rpath}, timeout=60).status_code, rname)
            code, j = meta(rpath)
        ok = j.get('md5') == lmd5 and j.get('size') == lsize
        print('  ', rname, 'MD5 OK' if ok else f"MISMATCH remote={j.get('md5')} {j.get('size')}", j.get('public_url'))
        e = dict(v, disk_path=rpath, size=lsize, md5=lmd5, remote_md5_ok=ok, public_url=j.get('public_url'), public_key=j.get('public_key'))
        with lock:
            results.append(e)
            checkpoint()
        return e

    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(job, v) for v in sorted(plan, key=lambda v: -(v.get('size') or 0))]
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as e:  # noqa: BLE001
                print('JOB FAILED', repr(e)[:300])
    code, j = meta(folder)
    if not j.get('public_url'):
        print('publish folder', requests.put(f'{API}/resources/publish', headers=H, params={'path': folder}, timeout=60).status_code)
        code, j = meta(folder)
    print('FOLDER', j.get('public_url'))
    print('ALL DONE', len(results), 'bad md5:', sum(1 for e in results if not e['remote_md5_ok']))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    if len(sys.argv) >= 6 and sys.argv[1] == 'plan':
        make_plan(*sys.argv[2:6])
    elif len(sys.argv) >= 4 and sys.argv[1] == 'upload' and '--folder' in sys.argv:
        upload(sys.argv[2], sys.argv[3], sys.argv[sys.argv.index('--folder') + 1])
    else:
        raise SystemExit(__doc__)
