// Hand-drawn reaction icons (64x64 box, centre 32,32). Strokes draw on like a marker, then the
// accent fill lands slightly offset (sketch hatch look), exactly the deck's doodle language.
import React from 'react';
import {Draw} from '../components/Sketch';
import {wobble} from './hand';

export type IconKind = 'heart' | 'fire' | 'laugh' | 'thumb' | 'clap' | 'party' | 'hundred' | 'star' | 'muscle' | 'pray';

export const EMOJI_TO_ICON: Record<string, IconKind> = {
  '❤️': 'heart',
  '❤': 'heart',
  '🔥': 'fire',
  '😁': 'laugh',
  '😂': 'laugh',
  '🤣': 'laugh',
  '😄': 'laugh',
  '😅': 'laugh',
  '👍': 'thumb',
  '👏': 'clap',
  '🎉': 'party',
  '💯': 'hundred',
  '💪': 'star',
  '🙏': 'heart',
};

type Shape = {strokes: string[]; fills: {d: string; color: string}[]};

const heart = 'M32 54 C18 44 8 35 8 24 C8 15 15 10 22 10 C27 10 30 13 32 17 C34 13 37 10 42 10 C49 10 56 15 56 24 C56 35 46 44 32 54 Z';
const star = (cx: number, cy: number, R: number, r: number) => {
  let d = '';
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const rad = i % 2 ? r : R;
    d += `${i ? 'L' : 'M'}${(cx + Math.cos(a) * rad).toFixed(1)} ${(cy + Math.sin(a) * rad).toFixed(1)} `;
  }
  return d + 'Z';
};

export const SHAPES = (seed: string): Record<IconKind, Shape> => ({
  heart: {strokes: [heart, wobble([[44, 18], [48, 24]], seed + 'h', 0.5)], fills: [{d: heart, color: '#F26941'}]},
  fire: {
    strokes: [
      'M32 58 C18 56 12 46 14 36 C16 27 22 24 22 14 C30 20 34 26 32 34 C36 30 38 26 38 20 C46 28 52 38 50 46 C48 54 42 58 32 58 Z',
      'M32 56 C26 54 24 48 26 43 C28 39 30 38 30 33 C35 37 38 42 38 47 C38 52 36 55 32 56 Z',
    ],
    fills: [
      {d: 'M32 58 C18 56 12 46 14 36 C16 27 22 24 22 14 C30 20 34 26 32 34 C36 30 38 26 38 20 C46 28 52 38 50 46 C48 54 42 58 32 58 Z', color: '#F26941'},
      {d: 'M32 56 C26 54 24 48 26 43 C28 39 30 38 30 33 C35 37 38 42 38 47 C38 52 36 55 32 56 Z', color: '#FFD014'},
    ],
  },
  laugh: {
    strokes: [
      'M32 6 C47 6 58 17 58 32 C58 47 47 58 32 58 C17 58 6 47 6 32 C6 17 17 6 32 6 Z',
      'M17 26 Q21 20 25 26',
      'M39 26 Q43 20 47 26',
      'M18 36 L46 36 C44 46 38 50 32 50 C26 50 20 46 18 36 Z',
    ],
    fills: [{d: 'M32 6 C47 6 58 17 58 32 C58 47 47 58 32 58 C17 58 6 47 6 32 C6 17 17 6 32 6 Z', color: '#FFD014'}],
  },
  thumb: {
    strokes: [
      'M22 28 L30 10 C34 8 38 11 37 16 L35 26 L50 26 C55 26 57 30 56 34 L52 50 C51 54 48 56 44 56 L22 56 Z',
      'M10 28 L22 28 L22 56 L10 56 Z',
    ],
    fills: [{d: 'M22 28 L30 10 C34 8 38 11 37 16 L35 26 L50 26 C55 26 57 30 56 34 L52 50 C51 54 48 56 44 56 L22 56 Z', color: '#FFD014'}],
  },
  clap: {
    strokes: [
      'M20 56 C12 48 12 38 16 30 L26 14 C28 11 32 12 31 16 L27 26 L38 12 C40 9 44 11 42 15 L34 28 L44 18 C46 16 50 18 48 21 L38 34 L46 28 C49 26 52 29 49 32 L36 48 C31 55 25 58 20 56 Z',
      'M46 6 L48 12',
      'M54 10 L50 15',
      'M58 20 L52 21',
    ],
    fills: [{d: 'M20 56 C12 48 12 38 16 30 L26 14 C28 11 32 12 31 16 L27 26 L38 12 C40 9 44 11 42 15 L34 28 L44 18 C46 16 50 18 48 21 L38 34 L46 28 C49 26 52 29 49 32 L36 48 C31 55 25 58 20 56 Z', color: '#FFD014'}],
  },
  party: {
    strokes: ['M8 58 L22 18 L48 44 Z', 'M28 14 C30 8 36 8 36 4', 'M44 20 C50 16 56 20 60 16', 'M50 34 L58 32', 'M38 8 L40 12'],
    fills: [{d: 'M8 58 L22 18 L48 44 Z', color: '#F26941'}],
  },
  hundred: {
    strokes: ['M10 18 L16 14 L16 44', 'M30 14 C22 14 22 44 30 44 C38 44 38 14 30 14 Z', 'M48 14 C40 14 40 44 48 44 C56 44 56 14 48 14 Z', 'M8 52 Q32 46 56 52', 'M12 58 Q34 53 54 58'],
    fills: [],
  },
  star: {strokes: [star(32, 33, 26, 11)], fills: [{d: star(32, 33, 26, 11), color: '#FFD014'}]},
  muscle: {strokes: [star(32, 33, 26, 11)], fills: [{d: star(32, 33, 26, 11), color: '#FFD014'}]},
  pray: {strokes: [heart], fills: [{d: heart, color: '#F26941'}]},
});

// p = draw progress 0..1 (strokes), q = fill progress 0..1
export const SketchIcon: React.FC<{kind: IconKind; size: number; p: number; q: number; seed: string; ink?: string}> = ({kind, size, p, q, seed, ink = '#F4F1EA'}) => {
  const sh = SHAPES(seed)[kind] ?? SHAPES(seed).star;
  const n = sh.strokes.length;
  return (
    <svg width={size} height={size} viewBox="-4 -4 72 72" style={{overflow: 'visible', display: 'block'}}>
      {sh.fills.map((fl, i) => (
        <path key={`f${i}`} d={fl.d} fill={fl.color} opacity={q * 0.95} transform={`translate(${(1 - q) * 3 + 2} ${(1 - q) * 3 + 2})`} />
      ))}
      {sh.strokes.map((d, i) => {
        const a = i / n;
        const b = (i + 1) / n;
        const pp = Math.max(0, Math.min(1, (p - a) / (b - a)));
        return <Draw key={i} d={d} p={pp} stroke={ink} width={4.2} />;
      })}
    </svg>
  );
};
