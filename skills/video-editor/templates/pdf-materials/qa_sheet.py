"""Contact sheet of rendered PDF pages for visual QA: python qa_sheet.py <pdf> <pages 1,2,5> <out.png> [dpi] [cols]"""
import sys, fitz
from PIL import Image
import io
pdf, pages, out = sys.argv[1], [int(x) for x in sys.argv[2].split(',')], sys.argv[3]
dpi = int(sys.argv[4]) if len(sys.argv) > 4 else 50
cols = int(sys.argv[5]) if len(sys.argv) > 5 else min(4, len(pages))
d = fitz.open(pdf)
ims = [Image.open(io.BytesIO(d[p - 1].get_pixmap(dpi=dpi).tobytes('png'))).convert('RGB') for p in pages if p <= len(d)]
w, h = ims[0].size
rows = (len(ims) + cols - 1) // cols
s = Image.new('RGB', (cols * w + (cols - 1) * 8, rows * h + (rows - 1) * 8), (120, 120, 120))
for i, im in enumerate(ims):
    s.paste(im, ((i % cols) * (w + 8), (i // cols) * (h + 8)))
s.save(out)
print(out, s.size)
