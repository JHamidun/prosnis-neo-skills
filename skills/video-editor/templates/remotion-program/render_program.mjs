// Render Program EDLs in ONE node process (bundle once, one browser, per-EDL renderMedia).
// Usage: node render_program.mjs <bundleDir|--bundle> <outDir> <concurrency> <edl.json> [<edl.json> ...]
//   --bundle : (re)bundle src/index.ts into out/bundle first (bundle_lite.mjs: public_lite + hardlinks).
// For a long programme use split chunks + render_worker.mjs (several workers, lock files) instead.
// Resumable: an EDL whose <outDir>/<id>.video.mp4 exists is skipped.
import {bundleLite} from './bundle_lite.mjs';
import {openBrowser, renderMedia, selectComposition} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';

const [bArg, outDir, conc, ...edls] = process.argv.slice(2);
const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
let serveUrl = bArg;
if (bArg === '--bundle') {
  // light bundle (public_lite + hardlinked clips), never a full copy of public/ (G-R1)
  serveUrl = await bundleLite('out/bundle');
  log('bundled', serveUrl);
}
fs.mkdirSync(outDir, {recursive: true});
const browser = await openBrowser('chrome', {chromiumOptions: {gl: process.env.GL || 'angle'}});
for (const file of edls) {
  const edl = JSON.parse(fs.readFileSync(file, 'utf8'));
  const out = path.join(outDir, `${edl.id}.video.mp4`);
  if (fs.existsSync(out)) {
    log('skip (exists)', out);
    continue;
  }
  const tmp = out.replace('.mp4', '.part.mp4');
  const inputProps = {edl};
  const composition = await selectComposition({serveUrl, id: 'Program', inputProps, puppeteerInstance: browser});
  const ts = Date.now();
  let last = 0;
  await renderMedia({
    serveUrl,
    composition,
    inputProps,
    codec: 'h264',
    crf: 16,
    x264Preset: 'medium',
    imageFormat: 'jpeg',
    jpegQuality: 94,
    pixelFormat: 'yuv420p',
    colorSpace: 'bt709',
    outputLocation: tmp,
    concurrency: Number(conc),
    puppeteerInstance: browser,
    timeoutInMilliseconds: 300000,
    offthreadVideoCacheSizeInBytes: 2 * 1024 * 1024 * 1024,
    onProgress: ({renderedFrames}) => {
      if (renderedFrames - last >= 100) {
        last = renderedFrames;
        log(edl.id, renderedFrames, '/', composition.durationInFrames);
      }
    },
  });
  fs.renameSync(tmp, out);
  const s = (Date.now() - ts) / 1000;
  log('DONE', edl.id, composition.durationInFrames, 'frames in', s.toFixed(1), 's =', (composition.durationInFrames / s).toFixed(1), 'fps');
  fs.appendFileSync(path.join(outDir, 'render_times.jsonl'), JSON.stringify({id: edl.id, frames: composition.durationInFrames, seconds: +s.toFixed(1), fps: +(composition.durationInFrames / s).toFixed(2), concurrency: Number(conc), at: new Date().toISOString()}) + '\n');
}
await browser.close({silent: true});
log('ALL DONE');
