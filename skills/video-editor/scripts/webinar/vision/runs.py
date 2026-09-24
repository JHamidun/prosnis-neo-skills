"""Runs of equal frame-pass states (layout, share_kind, slide) of one source tag; used by refine_bounds.py.
usage: python runs.py --job job.json <tag>"""
import json,glob,sys,os
_sys_path_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, _sys_path_dir)
from job import load as _load_job  # noqa: E402
J = _load_job()
ROOT = f"{J.root}/vision"
def fmt(t): return f"{int(t//60):02d}:{t%60:04.1f}"
def runs(tag):
  st=[]
  for f in sorted(glob.glob(f'{ROOT}/frames_raw/{tag}_*.json')):
    d=json.load(open(f,encoding='utf-8'))
    bk={int(x['k']):x for x in d['result']['frames']}
    for it in d['items']:
      x=bk.get(it['k'],{}); st.append((it['t'],it['t_end'],x))
  st.sort(key=lambda z:z[0])
  out=[]
  for t,te,x in st:
    key=(x.get('layout'),x.get('share_kind'),x.get('slide_number'))
    if out and out[-1]['key']==key: out[-1]['te']=te; out[-1]['descs'].append(x.get('screen_desc') or '')
    else: out.append({'key':key,'t':t,'te':te,'descs':[x.get('screen_desc') or '']})
  return out
if __name__=='__main__':
  tag=sys.argv[1]
  for r in runs(tag):
    k=r['key']; print(f"{fmt(r['t'])}-{fmt(r['te'])} ({r['te']-r['t']:5.0f}s) {str(k[0])[:18]:18} {str(k[1])[:5]:5} s={k[2]} | {r['descs'][0][:70]}")
