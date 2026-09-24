import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {UI} from '../fonts';
import {C, T} from '../tokens';
import {easeExit} from './Layout';

const LT = T.lower_third;

// Name plate: navy card + coral bar. Enter = bar grows, card unmasks left->right, text rises;
// exit (half the time) = fade + slide down 12 px. Anchor = BOTTOM-LEFT point inside the feed.
export const LowerThird: React.FC<{person: string; from: number; to: number; anchor: number[]; oneLine?: boolean}> = ({
  person,
  from,
  to,
  anchor,
  oneLine = false,
}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (f < from || f > to) return null;
  const p = LT.people.find((x: any) => x.id === person);
  const s = spring({frame: f - from, fps, config: T.motion.spring_plate});
  const bar = interpolate(f - from, [0, 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  // text rides in WITH the plate wipe (an empty plate for 5+ frames read as a glitch in QA)
  const txt = spring({frame: f - from - 1, fps, config: {damping: 18, stiffness: 190, mass: 0.7}});
  const out = interpolate(f, [to - LT.exit_frames, to], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: easeExit});
  return (
    <div
      style={{
        position: 'absolute',
        left: anchor[0],
        bottom: 1080 - anchor[1],
        opacity: out,
        transform: `translateY(${(1 - out) * 12}px)`,
        display: 'flex',
        alignItems: 'stretch',
        filter: 'drop-shadow(0 10px 24px rgba(0,0,0,0.45))',
      }}
    >
      <div style={{width: LT.accent_bar[0], background: LT.accent_bar[1], borderRadius: 3, transform: `scaleY(${bar})`, transformOrigin: 'bottom'}} />
      <div
        style={{
          marginLeft: 8,
          background: LT.plate_bg,
          borderRadius: T.radius.plate,
          padding: `${LT.pad[0]}px ${LT.pad[1]}px`,
          clipPath: `inset(0 ${(1 - s) * 100}% 0 0 round ${T.radius.plate}px)`,
          outline: '1px solid rgba(201,203,224,0.12)',
          outlineOffset: -1,
        }}
      >
        <div style={{fontFamily: UI, fontWeight: 800, fontSize: LT.name_px, color: C.ink_on_dark, letterSpacing: '-0.01em', lineHeight: 1.15, transform: `translateY(${(1 - txt) * 10}px)`, opacity: txt}}>
          {p.name}
        </div>
        {(oneLine ? [p.role] : [p.role, p.role2]).filter(Boolean).map((r: string, i: number) => (
          <div
            key={i}
            style={{
              fontFamily: UI,
              fontWeight: LT.role_style.weight,
              fontSize: LT.role_style.px,
              lineHeight: LT.role_style.line_height,
              color: LT.role_style.color,
              marginTop: i === 0 ? 6 : 0,
              whiteSpace: 'nowrap',
              transform: `translateY(${(1 - txt) * (8 + i * 4)}px)`,
              opacity: txt,
            }}
          >
            {r}
          </div>
        ))}
      </div>
    </div>
  );
};
