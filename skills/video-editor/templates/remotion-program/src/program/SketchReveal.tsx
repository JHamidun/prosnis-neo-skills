// LIVE SKETCH reveal of a whole deck slide (engine of skill sketch-course-video: SVG strokeDashoffset
// over skeleton centre-lines reveals the ORIGINAL raster; long contours first, then accent hatching;
// the finished silhouette replaces the strokes). Elements start on spoken beats.
import React, {useEffect, useState} from 'react';
import {cancelRender, continueRender, delayRender, staticFile, useCurrentFrame} from 'remotion';
import {SketchSpec} from './types';

type P = {d: string; w: number; s: number; u: number; c: number};
type El = {id: string; label: string; kind: string; crop: number[]; paths: P[]; finish: string; ink_px: number; acc_px: number};
export type SketchData = {slide: number; src: string; w: number; h: number; theme: string; bg: string; elements: El[]};

const cache = new Map<string, SketchData>();
const pending = new Map<string, Promise<SketchData>>();

// fix4 (25.09): the art and the clean slide are drawn by SVG <image>, which Remotion does NOT wait for. Under render
// load a tab screenshotted frames before the PNG was decoded -> black/empty slide-window flashes at every
// sketch->slide settle (163 frames in 19 of 22 settles of v4). Recipe proven on the stories (0 dropouts / 5 videos):
// every PNG an SVG <image> uses is fetched + img.decode()'d BEFORE continueRender, the decoded HTMLImageElements
// stay alive for the tab's lifetime (module array), <image decoding="sync">, willChange on the cross-fading layer.
const decodedImgs: HTMLImageElement[] = [];
const decoding = new Map<string, Promise<void>>();
const decodeUrl = (url: string) => {
  if (!decoding.has(url)) {
    decoding.set(
      url,
      new Promise<void>((ok, bad) => {
        const im = new Image();
        decodedImgs.push(im);
        im.onload = () => {
          im.decode().catch(() => undefined).then(() => ok());
        };
        im.onerror = () => bad(new Error('art ' + url));
        im.src = url;
      }),
    );
  }
  return decoding.get(url)!;
};

// delayRender until an extra PNG (the clean slide of the settle cross-fade) is decoded in this tab.
const useDecoded = (path: string | undefined) => {
  const url = path ? staticFile(path) : undefined;
  const [handle] = useState(() => (url ? delayRender('decode ' + url) : null));
  useEffect(() => {
    if (!url || handle === null) return;
    decodeUrl(url)
      .then(() => continueRender(handle))
      .catch((e) => cancelRender(e));
  }, [url, handle]);
};

const load = (path: string) => {
  if (!pending.has(path)) {
    pending.set(
      path,
      fetch(staticFile(path))
        .then((r) => r.json())
        .then(async (d: SketchData) => {
          await decodeUrl(staticFile(d.src));
          cache.set(path, d);
          return d;
        }),
    );
  }
  return pending.get(path)!;
};

export const useSketch = (path: string | undefined) => {
  const [data, setData] = useState<SketchData | null>(path ? cache.get(path) ?? null : null);
  const [handle] = useState(() => (path && !cache.has(path) ? delayRender('sketch ' + path) : null));
  useEffect(() => {
    if (!path || data) return;
    load(path)
      .then((d) => {
        setData(d);
        if (handle !== null) continueRender(handle);
      })
      .catch((e) => cancelRender(e));
  }, [path, data, handle]);
  return data;
};

const clamp01 = (n: number) => Math.max(0, Math.min(1, n));
const pace = (p: number) => p + 0.021 * Math.sin(p * Math.PI * 2);

const firstX = (d: string) => {
  const m = d.match(/^M([\d.]+),/);
  return m ? Number(m[1]) : 0;
};
// Titles are written left -> right like a hand would (the tracer orders by contour length).
const ordered = new WeakMap<El, P[]>();
export const pathsOf = (e: El): P[] => {
  // text-bearing elements (titles, items with labels, footers) are written left -> right; pure
  // illustrations keep the tracer order (long outline first, then detail)
  if (e.kind === 'illustration' || e.kind === 'rest') return e.paths;
  const hit = ordered.get(e);
  if (hit) return hit;
  const tot = e.paths.reduce((a, p) => a + p.u, 0) || 1;
  let acc = 0;
  const out = [...e.paths]
    .sort((a, b) => firstX(a.d) - firstX(b.d))
    .map((p) => {
      const q = {...p, s: acc / tot, u: (p.u / tot) * 1.35};
      acc += p.u * 0.8;
      return q;
    });
  const mx = Math.max(...out.map((p) => p.s + p.u));
  const res = out.map((p) => ({...p, s: p.s / mx, u: p.u / mx}));
  ordered.set(e, res);
  return res;
};

export const defaultDur = (e: El) => {
  if (e.kind === 'rest') return 12;
  if (e.kind === 'title') return 24;
  const ink = e.ink_px + e.acc_px * 0.5;
  return Math.round(Math.max(16, Math.min(56, ink / 1500)));
};

export const elementTimes = (data: SketchData, spec: SketchSpec) => {
  // explicit beats win; elements without a beat follow the previous one (-4 f overlap)
  const out: Record<string, {start: number; dur: number}> = {};
  let cursor = Math.min(...Object.values(spec.beats));
  for (const e of data.elements) {
    const dur = spec.durs?.[e.id] ?? defaultDur(e);
    const start = spec.beats[e.id] ?? cursor;
    out[e.id] = {start, dur};
    cursor = Math.max(cursor, start + dur - 4);
  }
  return out;
};

const pointOn = (d: string, frac: number): [number, number] => {
  const pts = d
    .slice(1)
    .split(' L')
    .map((s) => s.split(',').map(Number) as [number, number]);
  const seg = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
  let rest = seg.reduce((a, b) => a + b, 0) * frac;
  for (let i = 0; i < seg.length; i++) {
    if (rest <= seg[i]) {
      const k = rest / (seg[i] || 1);
      return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k];
    }
    rest -= seg[i];
  }
  return pts[pts.length - 1];
};

// Physical marker (from the approved engine), accent = coral tip while hatching.
const Pen: React.FC<{x: number; y: number; accent: boolean}> = ({x, y, accent}) => (
  <g transform={`translate(${x} ${y}) rotate(-44) scale(1.05)`}>
    <path d="M3 6 L78 6 Q85 6 85 14 L85 27 Q85 32 77 32 L18 32 Z" fill="#000" opacity={0.18} />
    <path d="M0 0 L17 -8 L99 -8 Q111 -8 111 3 L111 8 Q111 17 100 17 L17 17 Z" fill="#252525" stroke="#727272" strokeWidth={1.5} />
    <path d="M3 1 L18 -4 L18 13 L3 6 Z" fill={accent ? '#F2C21B' : '#1B1A17'} />
    <path d="M21 -6 L81 -6 L81 15 L21 15 Z" fill="#E9E5D9" />
    <path d="M82 -7 L88 -7 L88 16 L82 16 Z" fill={accent ? '#F2C21B' : '#797875'} />
    <path d="M26 -2 L76 -2" fill="none" stroke="#FFF" strokeWidth={2} opacity={0.75} />
  </g>
);

// Renders in CONTENT space (data.w x data.h); the parent scales/punches it into the window.
export const SketchReveal: React.FC<{spec: SketchSpec; uid: string; slideImg?: string}> = ({spec, uid, slideImg}) => {
  const f = useCurrentFrame();
  const data = useSketch(spec.data);
  useDecoded(slideImg); // the clean slide is decoded in this tab before any frame of this feed is captured
  if (!data) return null;
  const times = elementTimes(data, spec);
  const lastEnd = Math.max(...Object.values(times).map((t) => t.start + t.dur));
  const settle = spec.settle ?? lastEnd + 6;
  const settleP = clamp01((f - settle) / 8);
  const pens = new Set(spec.pen ?? []);
  return (
    <svg width={data.w} height={data.h} viewBox={`0 0 ${data.w} ${data.h}`} style={{position: 'absolute', left: 0, top: 0, display: 'block'}}>
      <rect width={data.w} height={data.h} fill={data.bg} />
      {settleP < 1
        ? data.elements.map((e, i) => {
            const t = times[e.id];
            const u = (f - t.start) / t.dur;
            if (u <= 0) return null;
            const complete = u >= 1.08;
            const PS = pathsOf(e);
            const live = u < 1 ? PS.find((p) => u >= p.s && u < p.s + p.u) : undefined;
            const penO = Math.max(0, Math.min(1, (f - t.start) / 4, (t.start + t.dur * 1.02 - f) / 5));
            // pen stays on the element for its whole draw (parks at the end of the last stroke between
            // strokes) and fades in/out over 4-5 frames instead of popping
            const lastDone = !live && u < 1.02 ? [...PS].filter((p) => p.s <= u).sort((a, b) => b.s - a.s)[0] : undefined;
            const pt = pens.has(e.id)
              ? live
                ? pointOn(live.d, pace(clamp01((u - live.s) / live.u)))
                : lastDone
                  ? pointOn(lastDone.d, 1)
                  : null
              : null;
            const [x, y, w, h] = e.crop;
            const id = `${uid}-m${i}`;
            return (
              <g key={e.id}>
                <defs>
                  <mask id={id} maskUnits="userSpaceOnUse" x={x - 16} y={y - 16} width={w + 32} height={h + 32}>
                    {!complete
                      ? PS.map((p, k) => {
                          const q = pace(clamp01((u - p.s) / p.u));
                          return q > 0 ? (
                            <path key={k} d={p.d} stroke="white" fill="none" strokeWidth={p.w} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - q} />
                          ) : null;
                        })
                      : null}
                    <path d={e.finish} fill="white" opacity={clamp01((u - 1) / 0.08)} />
                  </mask>
                </defs>
                <image href={staticFile(data.src)} width={data.w} height={data.h} mask={`url(#${id})`} {...{decoding: 'sync'}} />
                {pt ? <g opacity={penO}><Pen x={pt[0]} y={pt[1]} accent={(live ?? lastDone)!.c === 1} /></g> : null}
              </g>
            );
          })
        : null}
      {settleP > 0 ? <image href={staticFile(slideImg ?? data.src)} width={data.w} height={data.h} opacity={settleP} style={{willChange: 'opacity'}} {...{decoding: 'sync'}} /> : null}
    </svg>
  );
};

// Selected elements of a slide drawn as a standalone illustration (chapter cards, "around the
// slide" callouts). viewBox = union of the element crops, fitted into `box` (stage px).
// blend: 'lighten' on dark cards (black art background disappears), 'darken' on paper cards.
export const SketchArt: React.FC<{data: string; ids: string[]; start: number; box: [number, number, number, number]; uid: string; blend?: 'lighten' | 'darken'; speed?: number}> = ({
  data: path,
  ids,
  start,
  box,
  uid,
  blend = 'lighten',
  speed = 1,
}) => {
  const f = useCurrentFrame();
  const data = useSketch(path);
  if (!data) return null;
  const els = data.elements.filter((e) => ids.includes(e.id));
  if (!els.length) return null;
  const x0 = Math.min(...els.map((e) => e.crop[0])) - 12;
  const y0 = Math.min(...els.map((e) => e.crop[1])) - 12;
  const x1 = Math.max(...els.map((e) => e.crop[0] + e.crop[2])) + 12;
  const y1 = Math.max(...els.map((e) => e.crop[1] + e.crop[3])) + 12;
  let cursor = start;
  return (
    <svg
      width={box[2]}
      height={box[3]}
      viewBox={`${x0} ${y0} ${x1 - x0} ${y1 - y0}`}
      preserveAspectRatio="xMidYMid meet"
      style={{position: 'absolute', left: box[0], top: box[1], mixBlendMode: blend, overflow: 'visible'}}
    >
      {els.map((e, i) => {
        const dur = Math.round(defaultDur(e) * speed);
        const t0 = cursor;
        cursor += Math.max(8, dur - 6);
        const u = (f - t0) / dur;
        if (u <= 0) return null;
        const complete = u >= 1.08;
        const [x, y, w, h] = e.crop;
        const id = `${uid}-a${i}`;
        return (
          <g key={e.id}>
            <defs>
              <mask id={id} maskUnits="userSpaceOnUse" x={x - 16} y={y - 16} width={w + 32} height={h + 32}>
                {!complete
                  ? pathsOf(e).map((p, k) => {
                      const q = pace(clamp01((u - p.s) / p.u));
                      return q > 0 ? (
                        <path key={k} d={p.d} stroke="white" fill="none" strokeWidth={p.w} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - q} />
                      ) : null;
                    })
                  : null}
                <path d={e.finish} fill="white" opacity={clamp01((u - 1) / 0.08)} />
              </mask>
            </defs>
            <image href={staticFile(data.src)} width={data.w} height={data.h} mask={`url(#${id})`} {...{decoding: 'sync'}} />
          </g>
        );
      })}
    </svg>
  );
};
