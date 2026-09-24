// Stills of Program EDL frames in one process. Usage: node still_edl.mjs <bundleDir|--bundle> <outDir> <edl.json>:<f1,f2,...> [...]
import {bundleLite} from './bundle_lite.mjs';
import {openBrowser, renderStill, selectComposition} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';
const [bArg, outDir, ...jobs] = process.argv.slice(2);
const t0 = Date.now();
let serveUrl = bArg;
if (bArg === '--bundle') {
  // light bundle (public_lite + hardlinked clips), never a full copy of public/ (G-R1)
  serveUrl = await bundleLite('out/bundle');
  console.log('bundled', ((Date.now() - t0) / 1000).toFixed(1), 's');
}
fs.mkdirSync(outDir, {recursive: true});
const browser = await openBrowser('chrome');
for (const job of jobs) {
  const i = job.lastIndexOf(':');
  const file = job.slice(0, i);
  const frames = job.slice(i + 1).split(',').map(Number);
  const edl = JSON.parse(fs.readFileSync(file, 'utf8'));
  const inputProps = {edl};
  const composition = await selectComposition({serveUrl, id: 'Program', inputProps, puppeteerInstance: browser});
  for (const fr of frames) {
    const output = path.join(outDir, `${edl.id}_f${String(fr).padStart(4, '0')}.png`);
    const t = Date.now();
    await renderStill({serveUrl, composition, inputProps, frame: fr, output, puppeteerInstance: browser, timeoutInMilliseconds: 240000});
    console.log('OK', output, Date.now() - t, 'ms');
  }
}
await browser.close({silent: true});
