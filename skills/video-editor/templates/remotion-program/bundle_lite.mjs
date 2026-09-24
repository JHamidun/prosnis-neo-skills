// Light bundle: webpack bundle from public_lite/ (fonts, brand, slides, art, sketch JSON - tens of MB)
// and then HARDLINK every heavy file that exists in public/ but not in the bundle (full/clips/*.mp4,
// full/video/*.mp4 ...) into <bundle>/public. bundle({publicDir: 'public'}) physically copies the whole
// public folder (5+ GB of ingested clips on a 2-hour webinar) - minutes and gigabytes per re-bundle
// (gotcha G-R1). Hardlinks cost nothing and need the bundle on the same volume as public/.
// fs.linkSync = CreateHardLinkW: works with Cyrillic paths, unlike `cmd /c mklink` in a Cyrillic console.
//
// Usage (from the remotion project dir):
//   node bundle_lite.mjs <outDir> [--public-lite public_lite] [--link-from public] [--no-link]
// As a module: import {bundleLite} from './bundle_lite.mjs'; await bundleLite('out/bundle')
// After ANY change of style/tokens.json or src/** make a NEW bundle (tokens are baked in, G-R2).
import {bundle} from '@remotion/bundler';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const walk = (dir, base = dir, out = []) => {
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, {withFileTypes: true})) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, base, out);
    else out.push(path.relative(base, p));
  }
  return out;
};

export const linkMissing = (fromDir, bundleDir) => {
  const pub = path.join(bundleDir, 'public');
  let linked = 0;
  let bytes = 0;
  for (const rel of walk(fromDir)) {
    const dst = path.join(pub, rel);
    if (fs.existsSync(dst)) continue;
    fs.mkdirSync(path.dirname(dst), {recursive: true});
    const src = path.join(fromDir, rel);
    try {
      fs.linkSync(src, dst);
    } catch (e) {
      // different volume or FS without hardlinks: fall back to a copy, but say so loudly
      console.warn('hardlink failed, copying', rel, String(e.code || e));
      fs.copyFileSync(src, dst);
    }
    linked += 1;
    bytes += fs.statSync(dst).size;
  }
  return {linked, bytes};
};

export const bundleLite = async (outDir, {publicLite = 'public_lite', linkFrom = 'public', link = true} = {}) => {
  const t = Date.now();
  const out = await bundle({entryPoint: path.resolve('src/index.ts'), outDir: path.resolve(outDir), publicDir: path.resolve(publicLite)});
  let info = {linked: 0, bytes: 0};
  if (link && fs.existsSync(path.resolve(linkFrom))) info = linkMissing(path.resolve(linkFrom), out);
  console.log('bundled', out, ((Date.now() - t) / 1000).toFixed(1), 's; hardlinked', info.linked, 'files', (info.bytes / 1e9).toFixed(2), 'GB');
  return out;
};

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const outDir = args[0];
  if (!outDir || outDir.startsWith('--')) {
    console.error('usage: node bundle_lite.mjs <outDir> [--public-lite public_lite] [--link-from public] [--no-link]');
    process.exit(2);
  }
  const opt = (name, def) => {
    const i = args.indexOf(name);
    return i >= 0 ? args[i + 1] : def;
  };
  await bundleLite(outDir, {publicLite: opt('--public-lite', 'public_lite'), linkFrom: opt('--link-from', 'public'), link: !args.includes('--no-link')});
}
