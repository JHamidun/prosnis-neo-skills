"""Generate story-v3 sketch illustrations with Nano Banana 2 (rules/dont-do.md #11 default).

    python gen_art.py <spec.json>

spec.json: [{"out": "path.png", "theme": "paper"|"dark", "aspect": "1:1"|"16:9"|"9:16", "subject": "..."}]
Beside every PNG a .json with model, full prompt and sha256. Real PNG bytes whatever the model returns.
"""
import hashlib
import io
import json
import os
import sys
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

MODEL = 'gemini-3.1-flash-image-preview'
# Style copied from the Codex prompt behind the approved 23.09 story sheet (session 01a0c9bc, 18:06 UTC):
# graphite/black pencil, crosshatching, restrained coral scribbles — NOT navy ink, NOT smooth vector art.
STYLE = {
    'paper': ("uniform light warm paper background, exact color #F8F3EC everywhere around the drawing. Beautiful loose "
              "HUMAN hand-drawn irregular graphite and ink contours, rough confident BLACK pencil lines, crosshatched "
              "pencil shading, restrained CORAL ORANGE #F26941 scribbled colored-pencil highlights and fills"),
    'dark': ("absolutely pure BLACK #000000 background everywhere around the drawing. Beautiful loose HUMAN hand-drawn "
             "irregular WHITE chalk / colored-pencil contours, crosshatched shading, restrained CORAL ORANGE #F26941 "
             "scribbled fill hatching"),
}
TAIL = ("Authentic editorial sketchbook artwork for a hand-drawn pencil/marker animated explainer, ready for "
        "path-tracing animation. NOT smooth vector art, NOT flat icons, NOT 3D. No text, no letters, no numbers, "
        "no labels, no typography, no logos, no real people. Consistent medium-thickness sketch strokes, spacious "
        "simple composition occupying the inner 70% of the canvas, nothing touching the edges, no border.")


def key():
    """GOOGLE_API_KEY from the environment, else from $STORY_ENV_FILE (KEY=VALUE lines)."""
    os.environ.pop('GEMINI_API_KEY', None)          # conflicts with GOOGLE_API_KEY in the SDK
    if os.environ.get('GOOGLE_API_KEY'):
        return os.environ['GOOGLE_API_KEY']
    env = Path(os.environ.get('STORY_ENV_FILE', ''))
    if env.is_file():
        for line in env.read_text(encoding='utf-8').splitlines():
            if line.startswith('GOOGLE_API_KEY='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    raise SystemExit('GOOGLE_API_KEY missing (environment or STORY_ENV_FILE)')


def main():
    spec = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    client = genai.Client(api_key=key())
    for item in spec:
        out = Path(item['out'])
        if out.exists():
            print('exists, skip', out)
            continue
        prompt = (f"One coherent {item['aspect']} instructional exec-sketch illustration on a {STYLE[item['theme']]}. "
                  f"Subject: {item['subject']} {TAIL}")
        resp = client.models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(response_modalities=['IMAGE', 'TEXT'],
                                               image_config=types.ImageConfig(aspect_ratio=item['aspect'])))
        saved = False
        for part in resp.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                img = Image.open(io.BytesIO(part.inline_data.data))
                out.parent.mkdir(parents=True, exist_ok=True)
                img.convert('RGB').save(out, 'PNG')
                meta = {'model': MODEL, 'prompt': prompt, 'theme': item['theme'], 'model_format': img.format,
                        'size': img.size, 'sha256': hashlib.sha256(out.read_bytes()).hexdigest()}
                out.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
                print('saved', out, img.format, img.size, flush=True)
                saved = True
                break
        if not saved:
            raise SystemExit(f'no image for {out}: {resp.candidates[0].content.parts}')


if __name__ == '__main__':
    main()
