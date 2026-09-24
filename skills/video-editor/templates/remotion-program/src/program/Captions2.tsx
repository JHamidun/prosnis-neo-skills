// Karaoke captions (full-frame architecture E): whole cue fades in, every word lights up at the
// moment it is spoken (upcoming words dim), ONE key term per cue gets the coral marker pill that
// grows left->right on its spoken frame (reference behaviour of sketch-course-video captions).
import React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {UI} from '../fonts';
import {T} from '../tokens';
import {CapCue, CapWord} from './types';

const cap = T.captions;
const H = cap.highlight;
const ease = Easing.bezier(0.16, 1, 0.3, 1);
const cl = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

export const Captions2: React.FC<{words: CapWord[]; cues: CapCue[]; band: {center_x: number; max_width: number; top: number; bottom: number}; hidden?: boolean}> = ({
  words,
  cues,
  band,
  hidden,
}) => {
  const f = useCurrentFrame();
  const cue = cues.find((c) => f >= c.start && f < c.end);
  if (!cue || hidden) return null;
  const size = cap.size_studio;
  const fadeIn = interpolate(f, [cue.start, cue.start + cap.fade_in_frames], [0, 1], cl);
  const fadeOut = interpolate(f, [cue.end - cap.fade_out_frames, cue.end], [1, 0], cl);
  const rise = (1 - fadeIn) * cap.rise_px;
  const lineH = Math.round(size * cap.line_height);
  const blockH = cue.lines.length * lineH;
  const top = band.top + Math.round((band.bottom - band.top - blockH) / 2);
  return (
    <div
      style={{
        position: 'absolute',
        left: band.center_x - band.max_width / 2,
        width: band.max_width,
        top,
        opacity: Math.min(fadeIn, fadeOut),
        transform: `translateY(${rise}px)`,
        textAlign: 'center',
        fontFamily: UI,
        fontWeight: 700,
        fontSize: size,
        lineHeight: `${lineH}px`,
        letterSpacing: '-0.005em',
      }}
    >
      {cue.lines.map((line, li) => (
        <div key={li} style={{whiteSpace: 'pre'}}>
          {line.map((wi, k) => {
            const w = words[wi];
            const sp = k < line.length - 1 ? ' ' : '';
            const lit = interpolate(f, [w.s - 1, w.s + 2], [0, 1], cl);
            const color = `rgba(244,241,234,${0.42 + 0.58 * lit})`;
            if (!w.key) return (
              <span key={k} style={{color, textShadow: '0 2px 10px rgba(0,0,0,0.5)'}}>
                {w.w + sp}
              </span>
            );
            const g = interpolate(f, [w.s - H.lead_frames, w.s - H.lead_frames + H.grow_frames], [0, 1], {...cl, easing: ease});
            const m = w.w.match(/^([«"(]*)(.*?)([»"),.!?:;…]*)$/) || ['', '', w.w, ''];
            return (
              <span key={k} style={{color}}>
                {m[1]}
                <span style={{position: 'relative', zIndex: 0, display: 'inline-block', color}}>
                  <span
                    style={{
                      position: 'absolute',
                      zIndex: -1,
                      left: -H.pad_x - 2,
                      right: -H.pad_x - 2,
                      top: H.pad_y + 1,
                      bottom: H.pad_y - 3,
                      borderRadius: H.radius,
                      background: H.pill_color,
                      transformOrigin: 'left center',
                      transform: `scaleX(${g}) rotate(-0.6deg)`,
                    }}
                  />
                  {m[2]}
                  {g > 0 ? (
                    <span style={{position: 'absolute', left: 0, top: 0, color: H.text_on_pill, clipPath: `inset(-10px ${(1 - g) * 100}% -10px -10px)`}}>{m[2]}</span>
                  ) : null}
                </span>
                {m[3] + sp}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
};
