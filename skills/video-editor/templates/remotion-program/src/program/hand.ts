// Deterministic hand-drawn path generators (marker look: confident, slightly imperfect, round caps).
// Everything is seeded with remotion.random -> identical on every render / chunk.
import {random} from 'remotion';

const r = (seed: string, k: string) => random(`${seed}:${k}`) - 0.5;

// Marker ellipse: starts at ~200°, runs 1.12 turns so the end overshoots the start (like a real
// hand), radius wobbles with two low harmonics, slight tilt.
export const handEllipse = (cx: number, cy: number, rx: number, ry: number, seed: string) => {
  const turns = 1.12 + r(seed, 't') * 0.06;
  const a0 = (200 + r(seed, 'a') * 30) * (Math.PI / 180);
  const tilt = r(seed, 'tilt') * 0.12;
  const h1 = r(seed, 'h1') * 0.07;
  const h2 = r(seed, 'h2') * 0.05;
  const ph = r(seed, 'ph') * 6;
  const n = 110;
  let d = '';
  for (let i = 0; i <= n; i++) {
    const u = i / n;
    const a = a0 + u * turns * Math.PI * 2;
    // spiral in slightly so the overshoot sits inside/outside the start, not on top of it
    const k = 1 + h1 * Math.sin(a * 2 + ph) + h2 * Math.sin(a * 3 + ph * 1.7) - 0.05 * u;
    const x = rx * k * Math.cos(a);
    const y = ry * k * Math.sin(a);
    const xr = cx + x * Math.cos(tilt) - y * Math.sin(tilt);
    const yr = cy + x * Math.sin(tilt) + y * Math.cos(tilt);
    d += `${i ? 'L' : 'M'}${xr.toFixed(1)} ${yr.toFixed(1)} `;
  }
  return d;
};

// Wobbly polyline through points (quadratic segments with seeded control jitter).
export const wobble = (pts: [number, number][], seed: string, amp = 2.5) => {
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    const cx = (x0 + x1) / 2 + r(seed, `cx${i}`) * amp * 2;
    const cy = (y0 + y1) / 2 + r(seed, `cy${i}`) * amp * 2;
    d += ` Q${cx.toFixed(1)} ${cy.toFixed(1)} ${x1.toFixed(1)} ${y1.toFixed(1)}`;
  }
  return d;
};

// Two-pass marker underline (out + short return stroke), slightly rising to the right.
export const handUnderline = (x0: number, x1: number, y: number, seed: string) => {
  const a = wobble([[x0, y + 3], [(x0 + x1) / 2, y + r(seed, 'm') * 3], [x1, y - 3]], seed + 'a', 2);
  const b = wobble([[x1 - (x1 - x0) * 0.08, y + 6], [x0 + (x1 - x0) * 0.3, y + 10]], seed + 'b', 2);
  return [a, b];
};

export const handCheck = (x: number, y: number, s: number, seed: string) =>
  wobble([[x, y + s * 0.45], [x + s * 0.32, y + s * 0.8], [x + s, y]], seed, s * 0.03);

export const handBox = (x: number, y: number, w: number, h: number, seed: string) =>
  wobble(
    [
      [x - 4, y + 2],
      [x + w + 3, y - 3],
      [x + w + 2, y + h + 4],
      [x - 3, y + h + 1],
      [x + 6, y - 5],
    ],
    seed,
    3,
  );

export const handStrike = (x0: number, x1: number, y: number, seed: string) => wobble([[x0 - 6, y + 4], [x1 + 6, y - 4]], seed, 2);

// Curved arrow shaft + two-stroke head; returns [shaft, headL, headR]. bend>0 bows to the left of travel.
export const handArrow = (x0: number, y0: number, x1: number, y1: number, bend: number, seed: string, head = 20) => {
  const mx = (x0 + x1) / 2;
  const my = (y0 + y1) / 2;
  const dx = x1 - x0;
  const dy = y1 - y0;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  const cx = mx + nx * bend + r(seed, 'c') * 6;
  const cy = my + ny * bend + r(seed, 'd') * 6;
  const shaft = `M${x0.toFixed(1)} ${y0.toFixed(1)} Q${cx.toFixed(1)} ${cy.toFixed(1)} ${x1.toFixed(1)} ${y1.toFixed(1)}`;
  const ang = Math.atan2(y1 - cy, x1 - cx);
  const hl = `M${x1.toFixed(1)} ${y1.toFixed(1)} L${(x1 - Math.cos(ang - 0.5) * head).toFixed(1)} ${(y1 - Math.sin(ang - 0.5) * head).toFixed(1)}`;
  const hr = `M${x1.toFixed(1)} ${y1.toFixed(1)} L${(x1 - Math.cos(ang + 0.5) * head).toFixed(1)} ${(y1 - Math.sin(ang + 0.5) * head).toFixed(1)}`;
  return [shaft, hl, hr];
};

// Deck-style sparkle rays around a point (3 short strokes on one side).
export const handRays = (cx: number, cy: number, side: -1 | 1, seed: string, len = 26, r0 = 12) =>
  [-40, 0, 40].map((deg, i) => {
    const a = ((side === 1 ? deg : 180 - deg) * Math.PI) / 180;
    return wobble(
      [
        [cx + Math.cos(a) * r0, cy + Math.sin(a) * r0],
        [cx + Math.cos(a) * (r0 + len), cy + Math.sin(a) * (r0 + len)],
      ],
      `${seed}${i}`,
      1,
    );
  });

// Curly bracket along a side of a rect (vertical, opening to the right when side=1).
export const handBracket = (x: number, y0: number, y1: number, side: 1 | -1, seed: string) => {
  const m = (y0 + y1) / 2;
  const w = 16 * side;
  return wobble(
    [
      [x + w, y0],
      [x, y0 + 14],
      [x, m - 12],
      [x - w * 0.8, m],
      [x, m + 12],
      [x, y1 - 14],
      [x + w, y1],
    ],
    seed,
    1.2,
  );
};
