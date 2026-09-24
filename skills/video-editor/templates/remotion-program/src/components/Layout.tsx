import {Easing, interpolate} from 'remotion';
import {Rect, T} from '../tokens';

// Layout keyframes: [{frame, layout}] sorted by frame. A change of layout at frame F morphs
// over T.motion.layout_morph_frames starting at F (ease-in-out, no overshoot: it is a camera move,
// not a bounce).
export type LayoutKey = {frame: number; layout: string; morph?: number};

const M = T.motion;
export const easeMorph = Easing.bezier(0.65, 0, 0.35, 1);
export const easeEnter = Easing.bezier(0.16, 1, 0.3, 1);
export const easeExit = Easing.bezier(0.7, 0, 0.84, 0);

export const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
export const lerpRect = (a: Rect, b: Rect, p: number): Rect => [
  lerp(a[0], b[0], p),
  lerp(a[1], b[1], p),
  lerp(a[2], b[2], p),
  lerp(a[3], b[3], p),
];

export type LayoutState = {
  from: string;
  to: string;
  p: number; // 0..1 eased morph progress
  since: number; // frames since the morph started
  dur: number;
};

export const layoutAt = (keys: LayoutKey[], f: number): LayoutState => {
  let i = 0;
  for (let k = 0; k < keys.length; k++) if (keys[k].frame <= f) i = k;
  const cur = keys[i];
  const prev = i > 0 ? keys[i - 1] : cur;
  const dur = cur.morph ?? M.layout_morph_frames;
  const since = f - cur.frame;
  const p = i === 0 ? 1 : interpolate(since, [0, dur], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: easeMorph});
  return {from: prev.layout, to: cur.layout, p, since, dur};
};

const L = (name: string) => T.layout[name];

// Rect of a layout slot during a morph. Slots that are null in one of the layouts
// keep the rect of the other layout (their visibility is animated separately).
export const slotRect = (st: LayoutState, slot: string): Rect | null => {
  const a: Rect | null = L(st.from)[slot];
  const b: Rect | null = L(st.to)[slot];
  if (a && b) return lerpRect(a, b, st.p);
  return b || a;
};

// Opacity/offset of a slot that exists only on one side of the morph.
// Leaving: exits in chat_column_exit_frames from the morph start.
// Entering: enters in chat_column_enter_frames after chat_column_enter_delay.
export const slotPresence = (st: LayoutState, slot: string) => {
  const a = !!L(st.from)[slot];
  const b = !!L(st.to)[slot];
  if (a && b) return {o: 1, dx: 0};
  if (!a && !b) return {o: 0, dx: 0};
  if (a && !b) {
    const q = interpolate(st.since, [0, M.chat_column_exit_frames], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: easeExit});
    return {o: q, dx: (1 - q) * 32};
  }
  const q = interpolate(st.since, [M.chat_column_enter_delay, M.chat_column_enter_delay + M.chat_column_enter_frames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeEnter,
  });
  return {o: q, dx: (1 - q) * 40};
};

export const bandAt = (st: LayoutState) => {
  const a = L(st.from).caption_band;
  const b = L(st.to).caption_band;
  return {
    center_x: lerp(a.center_x, b.center_x, st.p),
    max_width: lerp(a.max_width, b.max_width, st.p),
    top: lerp(a.top, b.top, st.p),
    bottom: lerp(a.bottom, b.bottom, st.p),
  };
};
