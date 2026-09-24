import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {HAND, MONO, UI} from '../fonts';
import {C, Rect, T} from '../tokens';
import {easeEnter, easeExit, easeMorph, lerpRect} from './Layout';
import {Draw, arrow, markerUnderline, rays} from './Sketch';
import {SketchArt} from '../program/SketchReveal';

const CC = T.chapter_card;
const TL = CC.timeline;

export type ChapterProps = {
  n: number;
  time: string; // "24:15" = position in the FINAL video (also used for YouTube/RuTube chapters)
  lines: string[]; // title already split into <=2 balanced lines
  note?: string; // short handwritten note (Caveat), optional
  theme?: 'paper' | 'dark';
  fromRect?: Rect; // main-feed rect of the layout we come from
  toRect?: Rect; // main-feed rect of the layout we go to
  underlineW?: number; // px width of the last title line (measure offline); estimated if absent
  art?: {data: string; ids: string[]; box?: [number, number, number, number]; speed?: number}; // live sketch of the chapter's key illustration (right half)
};

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

// 3.6 s card that GROWS OUT OF the feed window and collapses back INTO the next one.
// Draw order follows the reference: container first, title, then strokes 10-20 f later.
export const ChapterCard: React.FC<ChapterProps> = ({
  n,
  time,
  lines,
  note,
  theme = 'dark',
  fromRect = T.layout.studio.main,
  toRect = T.layout.studio.main,
  underlineW,
  art: artSpec,
}) => {
  const f = useCurrentFrame();
  const paper = theme === 'paper';
  const bg = paper ? C.paper : C.navy;
  const ink = paper ? C.paper_ink : C.ink_on_dark;
  const soft = paper ? C.paper_muted : C.lavender;
  const full: Rect = [0, 0, 1920, 1080];

  const pin = interpolate(f, TL.morph_in, [0, 1], {...clamp, easing: easeMorph});
  const pout = interpolate(f, TL.morph_out, [0, 1], {...clamp, easing: easeMorph});
  const rect = f < TL.morph_out[0] ? lerpRect(fromRect, full, pin) : lerpRect(full, toRect, pout);
  const radius = f < TL.morph_out[0] ? T.radius.frame * (1 - pin) : T.radius.frame * pout;
  const contentOut = interpolate(f, [TL.morph_out[0] - 4, TL.morph_out[0] + 3], [1, 0], {...clamp, easing: easeExit});
  // the card turns transparent WHILE it collapses, so the next slide (already drawing under it)
  // shows through: no empty navy box between card and slide (QA r2)
  const cardOpacity = interpolate(f, [TL.morph_out[0] - 2, TL.morph_out[1] - 1], [1, 0], clamp);

  const label = interpolate(f, TL.label_in, [0, 1], {...clamp, easing: easeEnter});
  const px = CC.title.px;
  const lh = Math.round(px * 1.08);
  const titleTop = 540 - (lines.length * lh) / 2 - 10;
  const x0 = 180;
  const lastLen = lines[lines.length - 1].length;
  const uw = Math.min(1180, underlineW ?? lastLen * px * 0.6);
  const uy = titleTop + lines.length * lh + 18;
  const ul = interpolate(f, TL.underline_draw, [0, 1], {...clamp, easing: easeMorph});
  const art = (a: number, b: number) => interpolate(f, [a, b], [0, 1], {...clamp, easing: easeMorph});
  const numStr = String(n).padStart(2, '0');
  const numReveal = art(TL.art_draw[0], TL.art_draw[0] + 30);
  const numFill = art(TL.art_draw[0] + 26, TL.art_draw[1]);

  return (
    <AbsoluteFill style={{opacity: cardOpacity}}>
      <div
        style={{
          position: 'absolute',
          left: rect[0],
          top: rect[1],
          width: rect[2],
          height: rect[3],
          borderRadius: radius,
          overflow: 'hidden',
          background: bg,
          boxShadow: C.frame_shadow,
        }}
      >
        {/* content is laid out on the full 1920x1080 canvas and clipped by the growing window */}
        <div style={{position: 'absolute', left: -rect[0], top: -rect[1], width: 1920, height: 1080, opacity: contentOut}}>
          {paper ? null : (
            <div style={{position: 'absolute', inset: 0, background: `radial-gradient(900px 600px at 80% 70%, ${C.stage_glow}, transparent 70%)`}} />
          )}
          {artSpec ? <SketchArt data={artSpec.data} ids={artSpec.ids} start={TL.art_draw[0] - 8} box={artSpec.box ?? [1080, 190, 740, 700]} uid={`cc${n}`} blend={paper ? 'darken' : 'lighten'} speed={artSpec.speed ?? 0.7} /> : null}
          {/* giant outline chapter number, drawn left->right, then marker-filled */}
          <div
            style={{
              position: 'absolute',
              right: 150,
              top: 250,
              fontFamily: UI,
              fontWeight: 800,
              fontSize: artSpec ? 0 : 420,
              lineHeight: 1,
              letterSpacing: '-0.04em',
              color: 'transparent',
              WebkitTextStroke: `3px ${paper ? 'rgba(1,3,52,0.28)' : 'rgba(201,203,224,0.30)'}`,
              clipPath: `inset(0 ${(1 - numReveal) * 100}% 0 0)`,
            }}
          >
            {numStr}
          </div>
          <div
            style={{
              position: 'absolute',
              right: 150,
              top: 250,
              fontFamily: UI,
              fontWeight: 800,
              fontSize: artSpec ? 0 : 420,
              lineHeight: 1,
              letterSpacing: '-0.04em',
              color: paper ? 'rgba(242,105,65,0.16)' : 'rgba(242,105,65,0.14)',
              clipPath: `inset(${(1 - numFill) * 100}% 0 0 0)`,
            }}
          >
            {numStr}
          </div>
          {/* label */}
          <div
            style={{
              position: 'absolute',
              left: x0,
              top: titleTop - 70,
              fontFamily: MONO,
              fontWeight: 700,
              fontSize: CC.label.px,
              letterSpacing: '0.16em',
              color: C.coral,
              opacity: label,
              transform: `translateY(${(1 - label) * 10}px)`,
            }}
          >
            {`ГЛАВА ${numStr}  ·  ${time}`}
          </div>
          {/* title: each line unmasks left->right like a marker pass, 6 f stagger */}
          {lines.map((ln, i) => {
            const a = TL.title_reveal[0] + i * 6;
            const q = interpolate(f, [a, a + 20], [0, 1], {...clamp, easing: easeEnter});
            return (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  left: x0,
                  top: titleTop + i * lh,
                  fontFamily: UI,
                  fontWeight: CC.title.weight,
                  fontSize: px,
                  lineHeight: `${lh}px`,
                  letterSpacing: CC.title.tracking,
                  color: ink,
                  whiteSpace: 'nowrap',
                  clipPath: `inset(-20px ${(1 - q) * 100}% -20px 0)`,
                  transform: `translateX(${(1 - q) * -18}px)`,
                }}
              >
                {ln}
              </div>
            );
          })}
          <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
            <Draw d={markerUnderline(x0 - 6, x0 + uw, uy, `u${n}`)} p={ul} stroke={C.coral} width={CC.underline.stroke} />
            {rays(x0 - 44, titleTop + lh * 0.5, -1, `r${n}`, 30).map((d, i) => (
              <Draw key={i} d={d} p={art(TL.art_draw[0] + i * 3, TL.art_draw[0] + 14 + i * 3)} stroke={C.coral} width={5} />
            ))}
            {note
              ? arrow(x0 + 12, uy + 118, x0 + 70, uy + 40, -36, `a${n}`).map((d, i) => (
                  <Draw key={`a${i}`} d={d} p={art(44 + i * 4, 58 + i * 4)} stroke={soft} width={3.5} />
                ))
              : null}
          </svg>
          {note ? (
            <div
              style={{
                position: 'absolute',
                left: x0 + 96,
                top: uy + 88,
                fontFamily: HAND,
                fontSize: CC.hand_note.px,
                fontWeight: 600,
                color: soft,
                clipPath: `inset(-10px ${(1 - art(50, 66)) * 100}% -10px 0)`,
              }}
            >
              {note}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
