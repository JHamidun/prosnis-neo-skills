// Steady-state render speed probe (Remotion Node API, one process, timestamps per progress tick).
// Separates fixed start-up cost (node + browser + composition) from per-frame throughput.
// Usage: node speed.mjs <bundleDir> <compositionId> <out> <codec> <concurrency> [frames]
import {renderFrames, renderMedia, selectComposition, openBrowser} from '@remotion/renderer';
import fs from 'node:fs';

const [bundleDir, id, out, codec, conc, framesArg] = process.argv.slice(2);
const t0 = Date.now();
const log = [];
const mark = (what, extra = {}) => {
  const rec = {t_s: +((Date.now() - t0) / 1000).toFixed(2), what, ...extra};
  log.push(rec);
  console.log(JSON.stringify(rec));
};
mark('node_ready');
const browser = await openBrowser('chrome', {chromiumOptions: {gl: process.env.GL || null}});
mark('browser_open');
const composition = await selectComposition({serveUrl: bundleDir, id, puppeteerInstance: browser});
mark('composition', {frames: composition.durationInFrames});
const frameRange = framesArg ? framesArg.split('-').map(Number) : null;
let last = -1;
const ticks = [];
if (codec === 'png-seq') {
  // overlay frames straight to disk as RGBA PNG: no stitching (ProRes 4444 stitch cost ~2x the render)
  fs.mkdirSync(out, {recursive: true});
  await renderFrames({
    serveUrl: bundleDir,
    composition,
    outputDir: out,
    imageFormat: 'png',
    concurrency: Number(conc),
    puppeteerInstance: browser,
    frameRange,
    timeoutInMilliseconds: 240000,
    inputProps: composition.props,
    onStart: () => {},
    onFrameUpdate: (rendered) => {
      if (rendered % 25 === 0 && rendered !== last) {
        ticks.push({t_s: (Date.now() - t0) / 1000, renderedFrames: rendered});
        last = rendered;
      }
    },
  });
} else await renderMedia({
  serveUrl: bundleDir,
  composition,
  codec,
  outputLocation: out,
  concurrency: Number(conc),
  puppeteerInstance: browser,
  frameRange,
  imageFormat: codec === 'prores' ? 'png' : 'jpeg',
  jpegQuality: 92,
  proResProfile: codec === 'prores' ? '4444' : undefined,
  pixelFormat: codec === 'prores' ? 'yuva444p10le' : 'yuv420p',
  crf: codec === 'h264' ? 18 : undefined,
  x264Preset: codec === 'h264' ? 'veryfast' : undefined,
  timeoutInMilliseconds: 240000,
  onProgress: ({renderedFrames, encodedFrames, stitchStage}) => {
    if (renderedFrames !== last && renderedFrames % 25 === 0) {
      ticks.push({t_s: (Date.now() - t0) / 1000, renderedFrames, encodedFrames, stitchStage});
      last = renderedFrames;
    }
  },
});
mark('done');
await browser.close({silent: true});
const first = ticks.find((x) => x.renderedFrames >= 25);
const lastT = ticks[ticks.length - 1];
const steady = first && lastT && lastT.renderedFrames > first.renderedFrames
  ? (lastT.renderedFrames - first.renderedFrames) / (lastT.t_s - first.t_s)
  : null;
const summary = {gl: process.env.GL || 'default', machine: process.env.MACHINE || '', id, codec, concurrency: Number(conc), frames: lastT?.renderedFrames, startup_s: log.find((l) => l.what === 'composition').t_s,
  steady_fps: steady && +steady.toFixed(2), total_s: log[log.length - 1].t_s, ticks};
fs.appendFileSync(process.env.SPEED_LOG || 'speed_node.jsonl', JSON.stringify(summary) + '\n');  // one line per measured run
console.log('SUMMARY', JSON.stringify({...summary, ticks: undefined}));
