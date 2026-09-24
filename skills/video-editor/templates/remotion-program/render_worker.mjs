// Chunk render worker (Program comp, arch E). Several workers can run at once on the same list:
// each chunk is claimed with an exclusive lock file (<outDir>/<name>.lock, 'wx'), finished chunks
// (<outDir>/<name>.mp4) are skipped -> resumable. Clear stale *.lock before (re)starting workers.
// Usage: node render_worker.mjs <bundleDir> <outDir> <concurrency> <workerName> <edl.json> [<edl.json> ...]
// Output name: EDL id 'full_NNN' -> chunk_NNN.mp4, any other id -> <id>.mp4
import {openBrowser, renderMedia, selectComposition} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';

const [serveUrl, outDir, conc, worker, ...edls] = process.argv.slice(2);
const t0 = Date.now();
const stamp = () => new Date().toTimeString().slice(0, 8);
const log = (...a) => console.log(`[${stamp()} +${((Date.now() - t0) / 1000).toFixed(0)}s ${worker}]`, ...a);
fs.mkdirSync(outDir, {recursive: true});
let browser = null;
const getBrowser = async () => {
  if (!browser) browser = await openBrowser('chrome', {chromiumOptions: {gl: process.env.GL || 'angle'}});
  return browser;
};
for (const file of edls) {
  const edl = JSON.parse(fs.readFileSync(file, 'utf8'));
  const name = edl.id.startsWith('full_') ? edl.id.replace('full_', 'chunk_') : edl.id;
  const out = path.join(outDir, `${name}.mp4`);
  if (fs.existsSync(out)) continue;
  const lock = path.join(outDir, `${name}${process.env.LOCK_TAG ? '.' + process.env.LOCK_TAG : ''}.lock`);
  let fd;
  try {
    fd = fs.openSync(lock, 'wx');
  } catch {
    continue; // claimed by another worker
  }
  fs.writeSync(fd, `${worker} pid ${process.pid} ${new Date().toISOString()}\n`);
  fs.closeSync(fd);
  const tmp = path.join(outDir, `${name}.part.mp4`);
  const inputProps = {edl};
  const ts = Date.now();
  let last = 0;
  try {
    const b = await getBrowser();
    const composition = await selectComposition({serveUrl, id: 'Program', inputProps, puppeteerInstance: b});
    log('START', name, composition.durationInFrames, 'frames, c', conc);
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
      overwrite: true,
      concurrency: Number(conc),
      puppeteerInstance: b,
      timeoutInMilliseconds: 300000,
      offthreadVideoCacheSizeInBytes: 2 * 1024 * 1024 * 1024,
      onProgress: ({renderedFrames}) => {
        if (renderedFrames - last >= 500) {
          last = renderedFrames;
          const s = (Date.now() - ts) / 1000;
          log(name, renderedFrames, '/', composition.durationInFrames, (renderedFrames / s).toFixed(1), 'fps');
        }
      },
    });
    fs.renameSync(tmp, out);
    const s = (Date.now() - ts) / 1000;
    const fps = composition.durationInFrames / s;
    log('DONE', name, composition.durationInFrames, 'frames in', s.toFixed(1), 's =', fps.toFixed(2), 'fps');
    fs.appendFileSync(path.join(outDir, 'render_times.jsonl'), JSON.stringify({id: name, frames: composition.durationInFrames, seconds: +s.toFixed(1), fps: +fps.toFixed(2), concurrency: Number(conc), worker, at: new Date().toISOString()}) + '\n');
  } catch (e) {
    log('FAIL', name, String(e && e.stack ? e.stack : e).slice(0, 2000));
    fs.appendFileSync(path.join(outDir, 'render_errors.log'), `[${new Date().toISOString()}] ${worker} ${name}: ${String(e && e.stack ? e.stack : e).slice(0, 4000)}\n`);
    try { await browser?.close({silent: true}); } catch {}
    browser = null;
  } finally {
    try { fs.unlinkSync(lock); } catch {}
  }
}
try { await browser?.close({silent: true}); } catch {}
log('ALL DONE');
