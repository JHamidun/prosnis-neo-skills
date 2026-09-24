"""Videos embedded in a .pptx: slide number, shape, rectangle as fractions of the slide (from the shape's a:xfrm - the
TRUTH for where a video sits; an assets map of the deck builder can drift, G-P2), the media part and its md5 (to match
the embedded media with the original files).

usage: python pptx_video_rects.py <deck.pptx> [out.json] [--extract <dir>]
  out.json (default pptx_videos.json): {"W", "H", "videos": [{page, slide_xml, shape, descr, rect: [x, y, w, h], media,
                                          size, md5}]}
  --extract: also write every embedded media file to <dir> (name = basename of the media part)
Used by: pdf_video_links.py (buttons over the video areas of the exported PDF), the webinar montage (skill
video-editor, slides/vsync_motion.py crop of a silent deck video).
"""
import hashlib
import json
import posixpath
import sys
import zipfile
from pathlib import Path

from lxml import etree

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'p14': 'http://schemas.microsoft.com/office/powerpoint/2010/main'}


def scan(pptx):
    z = zipfile.ZipFile(pptx)
    pres = etree.fromstring(z.read('ppt/presentation.xml'))
    sz = pres.find('p:sldSz', NS)
    W, H = int(sz.get('cx')), int(sz.get('cy'))
    prels = etree.fromstring(z.read('ppt/_rels/presentation.xml.rels'))
    rid2t = {r.get('Id'): r.get('Target') for r in prels}
    out = []
    for i, s in enumerate(pres.find('p:sldIdLst', NS), 1):
        t = 'ppt/' + rid2t[s.get('{%s}id' % NS['r'])]
        x = etree.fromstring(z.read(t))
        relp = posixpath.join(posixpath.dirname(t), '_rels', posixpath.basename(t) + '.rels')
        rels = {r.get('Id'): (r.get('Target'), r.get('Type').split('/')[-1]) for r in etree.fromstring(z.read(relp))}
        title = ' '.join(x.xpath('.//a:t/text()', namespaces=NS))[:60]
        for pic in x.iter('{%s}pic' % NS['p']):
            vf = pic.find('.//a:videoFile', NS)
            if vf is None:
                continue
            rid = vf.get('{%s}link' % NS['r'])
            media = pic.find('.//p14:media', NS)
            mrid = media.get('{%s}embed' % NS['r']) if media is not None else None
            tgt = rels.get(mrid or rid)
            off = pic.find('.//a:xfrm/a:off', NS)
            ext = pic.find('.//a:xfrm/a:ext', NS)
            rect = [round(int(off.get('x')) / W, 4), round(int(off.get('y')) / H, 4), round(int(ext.get('cx')) / W, 4), round(int(ext.get('cy')) / H, 4)]
            nv = pic.find('.//p:cNvPr', NS)
            mpath = posixpath.normpath(posixpath.join(posixpath.dirname(t), tgt[0])) if tgt else None
            inside = bool(mpath) and mpath in z.namelist()
            out.append({'page': i, 'slide_xml': t, 'shape': nv.get('name'), 'descr': nv.get('descr'), 'rect': rect, 'media': mpath,
                        'size': z.getinfo(mpath).file_size if inside else None,
                        'md5': hashlib.md5(z.read(mpath)).hexdigest() if inside else None, 'slide_text': title})
    return z, {'W': W, 'H': H, 'slides': len(pres.find('p:sldIdLst', NS)), 'videos': out}


def main():
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and not sys.argv[i - 1].startswith('--')]
    if not pos:
        raise SystemExit(__doc__)
    z, res = scan(pos[0])
    out = Path(pos[1] if len(pos) > 1 else 'pptx_videos.json')
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    if '--extract' in sys.argv:
        d = Path(sys.argv[sys.argv.index('--extract') + 1])
        d.mkdir(parents=True, exist_ok=True)
        for v in res['videos']:
            if v['md5']:
                (d / posixpath.basename(v['media'])).write_bytes(z.read(v['media']))
    for v in res['videos']:
        print(v['page'], v['shape'], '|', v['descr'], v['rect'], v['media'], v['size'], v['md5'], '|', v['slide_text'])
    print('slides', res['slides'], 'videos', len(res['videos']), 'size', res['W'], res['H'], '->', out)


if __name__ == '__main__':
    main()
