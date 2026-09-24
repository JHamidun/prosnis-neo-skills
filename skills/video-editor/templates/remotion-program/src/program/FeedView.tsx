// One feed inside the main window: content space (cw x ch) -> window via a focus rect that can be
// punched in / panned (moves) and slowly drift (Ken Burns). Marks, blur and pulses live in content
// space, so they stay glued to the slide through punch-ins and layout morphs.
import React from 'react';
import {Img, Sequence, interpolate, staticFile} from 'remotion';
import {Vid} from './Vid';
import {Draw} from '../components/Sketch';
import {easeMorph, lerpRect} from '../components/Layout';
import {C, Rect} from '../tokens';
import {handArrow, handBox, handCheck, handEllipse, handStrike, handUnderline} from './hand';
import {SketchReveal} from './SketchReveal';
import {Feed, Mark} from './types';

const cl = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

export const focusAt = (feed: Feed, f: number): Rect => {
  let cur: Rect = feed.crop ?? [0, 0, feed.cw, feed.ch];
  for (const m of feed.moves ?? []) {
    if (f < m.frame) break;
    const p = interpolate(f, [m.frame, m.frame + (m.dur ?? 22)], [0, 1], {...cl, easing: easeMorph});
    cur = lerpRect(cur, m.rect, p);
  }
  if (feed.drift) {
    const s = 1 + Math.abs(feed.drift) * ((f - feed.from) / 250);
    const [x, y, w, h] = cur;
    const nw = w / s;
    const nh = h / s;
    // positive drift = push in to centre; negative = push in towards the left third (alternating feel)
    const ax = feed.drift > 0 ? 0.5 : 0.38;
    cur = [x + (w - nw) * ax, y + (h - nh) * 0.5, nw, nh];
  }
  return cur;
};

// content px -> window px (window-local), cover fit of the focus rect
export const contentToWindow = (win: Rect, focus: Rect) => {
  const k = Math.max(win[2] / focus[2], win[3] / focus[3]);
  const tx = win[2] / 2 - (focus[0] + focus[2] / 2) * k;
  const ty = win[3] / 2 - (focus[1] + focus[3] / 2) * k;
  return {k, tx, ty};
};

const MarkView: React.FC<{m: Mark; f: number; k: number; i: number; uid: string}> = ({m, f, k, i, uid}) => {
  if (f < m.from) return null;
  const dur = m.dur ?? (m.type === 'underline' ? 12 : m.type === 'arrow' ? 14 : m.type === 'check' ? 9 : 16);
  const p = interpolate(f, [m.from, m.from + dur], [0, 1], {...cl, easing: easeMorph});
  const out = m.to !== undefined ? interpolate(f, [m.to - 8, m.to], [1, 0], cl) : 1;
  if (out <= 0) return null;
  const col = m.color ?? C.coral;
  const sw = (m.width ?? 7) / k;
  const [x, y, w, h] = m.rect;
  const seed = m.seed ?? `${uid}mk${i}`;
  if (m.type === 'spotlight') {
    const a = interpolate(f, [m.from, m.from + 10], [0, 0.5], cl) * out;
    const r = 18 / k;
    return (
      <g>
        <defs>
          <mask id={`${uid}-spot${i}`}>
            <rect x={-5000} y={-5000} width={20000} height={20000} fill="white" />
            <rect x={x - 12 / k} y={y - 12 / k} width={w + 24 / k} height={h + 24 / k} rx={r} fill="black" />
          </mask>
        </defs>
        <rect x={-5000} y={-5000} width={20000} height={20000} fill="#000" opacity={a} mask={`url(#${uid}-spot${i})`} />
      </g>
    );
  }
  if (m.type === 'pulse') {
    const t = (f - m.from) / 25;
    const ring = 0.5 - 0.5 * Math.cos(Math.min(t, 2) * Math.PI * 2);
    return (
      <rect
        x={x - (10 + ring * 10) / k}
        y={y - (10 + ring * 10) / k}
        width={w + (20 + ring * 20) / k}
        height={h + (20 + ring * 20) / k}
        rx={20 / k}
        fill="none"
        stroke={col}
        strokeWidth={(4 + ring * 3) / k}
        opacity={(0.35 + 0.65 * (1 - ring)) * out * Math.min(1, t * 4)}
      />
    );
  }
  let paths: string[] = [];
  if (m.type === 'circle') paths = [handEllipse(x + w / 2, y + h / 2, w / 2 + 18 / k, h / 2 + 14 / k, seed)];
  if (m.type === 'underline') paths = handUnderline(x, x + w, y + h + 8 / k, seed);
  if (m.type === 'check') paths = [handCheck(x + w + 16 / k, y, Math.min(h, 60 / k), seed)];
  if (m.type === 'box') paths = [handBox(x, y, w, h, seed)];
  if (m.type === 'strike') paths = [handStrike(x, x + w, y + h / 2, seed)];
  if (m.type === 'arrow') {
    const side = m.from_side ?? 'left';
    const L = 150 / k;
    const [x1, y1] = side === 'left' ? [x - 10 / k, y + h / 2] : side === 'right' ? [x + w + 10 / k, y + h / 2] : side === 'top' ? [x + w / 2, y - 10 / k] : [x + w / 2, y + h + 10 / k];
    const [x0, y0] = side === 'left' ? [x1 - L, y1 + L * 0.45] : side === 'right' ? [x1 + L, y1 + L * 0.45] : side === 'top' ? [x1 - L * 0.5, y1 - L] : [x1 - L * 0.5, y1 + L];
    paths = handArrow(x0, y0, x1, y1, 30 / k, seed, 22 / k);
  }
  const n = paths.length;
  return (
    <g opacity={out}>
      {paths.map((d, j) => {
        // first stroke takes 75 % of the time, the rest share the tail (marker return / arrow head)
        const a = j === 0 ? 0 : 0.75 + ((j - 1) * 0.25) / Math.max(1, n - 1);
        const b = j === 0 ? (n > 1 ? 0.8 : 1) : Math.min(1, a + 0.25 / Math.max(1, n - 1) + 0.05);
        const pp = interpolate(p, [a, b], [0, 1], cl);
        return <Draw key={j} d={d} p={pp} stroke={col} width={sw} />;
      })}
    </g>
  );
};

export const FeedView: React.FC<{feed: Feed; f: number; win: Rect; opacity?: number; uid: string}> = ({feed, f, win, opacity = 1, uid}) => {
  const focus = focusAt(feed, f);
  const {k, tx, ty} = contentToWindow(win, focus);
  const {cw, ch} = feed;
  let content: React.ReactNode = null;
  if (feed.kind === 'zoom' || feed.kind === 'video') {
    content = (
      <>
        {feed.kind === 'video' && feed.slideImg ? <Img src={staticFile(feed.slideImg)} style={{position: 'absolute', left: 0, top: 0, width: cw, height: ch}} /> : null}
        <Sequence from={feed.from} durationInFrames={feed.to - feed.from} layout="none">
          <Vid
            src={staticFile(feed.src)}
            startFrom={feed.srcStart ?? 0}
            style={
              feed.kind === 'video' && feed.videoRect
                ? {position: 'absolute', left: feed.videoRect[0], top: feed.videoRect[1], width: feed.videoRect[2], height: feed.videoRect[3], objectFit: 'cover', borderRadius: 12}
                : {position: 'absolute', left: 0, top: 0, width: cw, height: ch}
            }
          />
        </Sequence>
      </>
    );
  } else if (feed.kind === 'sketch' && feed.sketch) {
    content = <SketchReveal spec={feed.sketch} uid={uid} slideImg={feed.slideImg} />;
  } else {
    content = <Img src={staticFile(feed.src)} style={{position: 'absolute', left: 0, top: 0, width: cw, height: ch}} />;
  }
  return (
    <div style={{position: 'absolute', left: 0, top: 0, width: win[2], height: win[3], overflow: 'hidden', opacity}}>
      <div style={{position: 'absolute', left: 0, top: 0, width: cw, height: ch, transformOrigin: '0 0', transform: `translate(${tx}px, ${ty}px) scale(${k})`}}>
        {content}
        {(feed.blur ?? []).map((b, i) =>
          (b.from === undefined || f >= b.from) && (b.to === undefined || f < b.to) ? (
            <div key={i} style={{position: 'absolute', left: b.rect[0], top: b.rect[1], width: b.rect[2], height: b.rect[3], backdropFilter: 'blur(22px)', background: 'rgba(20,20,30,0.25)', borderRadius: 8}} />
          ) : null,
        )}
        <svg width={cw} height={ch} viewBox={`0 0 ${cw} ${ch}`} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible'}}>
          {(feed.marks ?? []).map((m, i) => (
            <MarkView key={i} m={m} f={f} k={k} i={i} uid={uid} />
          ))}
        </svg>
      </div>
    </div>
  );
};
