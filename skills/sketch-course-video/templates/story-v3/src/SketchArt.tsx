import {staticFile, useCurrentFrame} from 'remotion';
import {CORAL} from './design';

// Engine copied from the approved 23.09 story (Codex work/story/src/SketchArt.tsx, v14 technique):
// original raster strokes are revealed through centerline masks, a pencil rides the active stroke.
export type Stroke = {points: number[][]; width: number; start: number; duration: number; color: boolean};
export type Art = {crop: number[]; paths: Stroke[]; finish: string};
export type Sheet = {source: string; sourceWidth: number; sourceHeight: number; arts: Record<string, Art>};
export const clamp = (v: number) => Math.min(1, Math.max(0, v));
const path = (points: number[][]) => points.map((p, i) => `${i ? 'L' : 'M'}${p[0]} ${p[1]}`).join(' ');

function pointOn(points: number[][], fraction: number) {
  const lengths = points.slice(1).map((p, i) => Math.hypot(p[0] - points[i][0], p[1] - points[i][1]));
  let rest = lengths.reduce((a, b) => a + b, 0) * fraction;
  for (let i = 0; i < lengths.length; i++) {
    if (rest <= lengths[i]) {
      const k = rest / (lengths[i] || 1);
      return [points[i][0] + (points[i + 1][0] - points[i][0]) * k, points[i][1] + (points[i + 1][1] - points[i][1]) * k];
    }
    rest -= lengths[i];
  }
  return points[points.length - 1];
}

function Pencil({x, y, color}: {x: number; y: number; color: boolean}) {
  return <g transform={`translate(${x} ${y}) rotate(-48) scale(1.15)`}>
    <path d="M6 7 L32 -7 L153 -7 L155 10 L33 14 Z" fill="#000" opacity=".18"/>
    <path d="M0 0 L26 -12 L151 -12 Q160 -12 160 -4 L160 6 Q160 14 151 14 L26 14 Z" fill={color ? CORAL : '#DAD5CA'} stroke="#3B3A34" strokeWidth="2"/>
    <path d="M0 0 L26 -12 L26 14 Z" fill="#D2AC7B"/>
    <path d="M0 0 L9 -4 L10 5 Z" fill={color ? CORAL : '#151713'}/>
    <path d="M32 -7 L142 -7" stroke="white" strokeWidth="3" opacity=".7"/>
    <path d="M142 -12 L142 14" stroke="#52534C" strokeWidth="8"/>
  </g>;
}

export function SketchArt({sheet, base, x, y, w, h, start = 8, duration = 70, pen = false, id}: {
  sheet: Sheet; base: string; x: number; y: number; w: number; h: number; start?: number; duration?: number; pen?: boolean; id: string;
}) {
  const f = useCurrentFrame();
  const art = sheet.arts.main;
  const u = (f - start) / duration;
  if (!art || u < 0) return null;
  const [sx, sy, sw, sh] = art.crop;
  const scale = Math.min(w / sw, h / sh);
  const offsetX = x + (w - sw * scale) / 2;
  const offsetY = y + (h - sh * scale) / 2;
  const mask = `mask-${id}`;
  const live = u < 1 ? art.paths.find(p => u >= p.start && u < p.start + p.duration) : undefined;
  const p = live ? pointOn(live.points, clamp((u - live.start) / live.duration)) : null;
  return <svg width="1080" height="1920" viewBox="0 0 1080 1920" style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
    <svg x={x} y={y} width={w} height={h} viewBox={`${sx} ${sy} ${sw} ${sh}`}>
      <defs><mask id={mask} maskUnits="userSpaceOnUse" x={sx} y={sy} width={sw} height={sh}>
        {u < 1.1 && art.paths.map((s, i) => {
          const v = clamp((u - s.start) / s.duration);
          return v > 0 ? <path key={i} d={path(s.points)} stroke="white" fill="none" strokeWidth={s.width} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - v}/> : null;
        })}
        <path d={art.finish} fill="white" fillRule="evenodd" opacity={clamp((u - 1) / .08)}/>
      </mask></defs>
      {/* decoding=sync: a repaint (e.g. the CTA fade reaching opacity 1) must not screenshot the strokes before the PNG is decoded */}
      <image href={staticFile(base + sheet.source)} width={sheet.sourceWidth} height={sheet.sourceHeight} mask={`url(#${mask})`} {...{decoding: 'sync'}}/>
    </svg>
    {pen && p && live && <Pencil x={offsetX + (p[0] - sx) * scale} y={offsetY + (p[1] - sy) * scale} color={live.color}/>}
  </svg>;
}
