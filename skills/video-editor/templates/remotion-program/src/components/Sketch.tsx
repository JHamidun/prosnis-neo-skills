import React from 'react';
import {random} from 'remotion';

// Hand-drawn stroke helpers (the reference draws everything with trim-path reveals:
// uniform stroke, round caps, slight organic wobble, no visible hand).

export const wobblyLine = (x0: number, y0: number, x1: number, y1: number, seed: string, wob = 3, segs = 6) => {
  let d = `M ${x0.toFixed(1)} ${y0.toFixed(1)}`;
  for (let i = 1; i <= segs; i++) {
    const t = i / segs;
    const x = x0 + (x1 - x0) * t;
    const y = y0 + (y1 - y0) * t;
    const tm = (i - 0.5) / segs;
    const cx = x0 + (x1 - x0) * tm + (random(`${seed}-cx${i}`) - 0.5) * wob * 2;
    const cy = y0 + (y1 - y0) * tm + (random(`${seed}-cy${i}`) - 0.5) * wob * 2;
    d += ` Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }
  return d;
};

// Marker underline: one stroke out + a shorter return stroke, like a real marker swipe.
export const markerUnderline = (x0: number, x1: number, y: number, seed: string) => {
  const a = wobblyLine(x0, y + 2, x1, y - 3, `${seed}a`, 2.5, 5);
  const b = wobblyLine(x1 - 14, y + 5, x0 + (x1 - x0) * 0.28, y + 9, `${seed}b`, 2.5, 4);
  return `${a} M ${b.slice(2)}`;
};

// Deck-style "rays" around a headline: three short strokes fanning out.
export const rays = (cx: number, cy: number, side: -1 | 1, seed: string, len = 34) => {
  const out: string[] = [];
  [-38, 0, 38].forEach((deg, i) => {
    const a = ((side === 1 ? deg : 180 - deg) * Math.PI) / 180;
    const r0 = 14;
    const x0 = cx + Math.cos(a) * r0;
    const y0 = cy + Math.sin(a) * r0;
    const x1 = cx + Math.cos(a) * (r0 + len);
    const y1 = cy + Math.sin(a) * (r0 + len);
    out.push(wobblyLine(x0, y0, x1, y1, `${seed}${i}`, 1.5, 2));
  });
  return out;
};

// Hand-drawn arrow: curved shaft + two-stroke head.
export const arrow = (x0: number, y0: number, x1: number, y1: number, bend: number, seed: string) => {
  const mx = (x0 + x1) / 2 + bend;
  const my = (y0 + y1) / 2 - Math.abs(bend) * 0.6;
  const shaft = `M ${x0} ${y0} Q ${mx} ${my} ${x1} ${y1}`;
  const ang = Math.atan2(y1 - my, x1 - mx);
  const h = 18;
  const l = `M ${x1} ${y1} L ${(x1 - Math.cos(ang - 0.45) * h).toFixed(1)} ${(y1 - Math.sin(ang - 0.45) * h).toFixed(1)}`;
  const r = `M ${x1} ${y1} L ${(x1 - Math.cos(ang + 0.45) * h).toFixed(1)} ${(y1 - Math.sin(ang + 0.45) * h).toFixed(1)}`;
  void seed;
  return [shaft, l, r];
};

// Trim-path reveal. p in 0..1. pathLength=1 normalises every path.
export const Draw: React.FC<{d: string; p: number; stroke: string; width: number; opacity?: number}> = ({d, p, stroke, width, opacity = 1}) => {
  if (p <= 0.001) return null;
  return (
    <path
      d={d}
      pathLength={1}
      fill="none"
      stroke={stroke}
      strokeWidth={width}
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeDasharray="1 1"
      strokeDashoffset={1 - Math.min(1, p)}
      opacity={opacity}
    />
  );
};
