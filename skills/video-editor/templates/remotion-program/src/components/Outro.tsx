import React from 'react';
import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {MONO, UI} from '../fonts';
import {BRAND, C, T} from '../tokens';
import {easeEnter, easeMorph} from './Layout';
import {Draw, arrow, markerUnderline, rays} from './Sketch';
import {Stage} from './Stage';

const O = T.outro;
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

// CTA end card, 16 s. Everything readable from a phone: 56+ px for the link, QR on paper.
// All texts, links and QR images come from tokens.outro (QR PNGs are generated from URLs by
// scripts/webinar/deliver/make_qr.py into public_lite/brand/).
export const Outro: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const at = (i: number) => Math.round(O.stagger_s[i] * fps);
  const rise = (i: number) => {
    const s = spring({frame: f - at(i), fps, config: T.motion.spring_plate});
    return {opacity: Math.min(1, s * 1.4), transform: `translateY(${(1 - s) * 22}px)`};
  };
  const ul = interpolate(f, [at(1) + 10, at(1) + 32], [0, 1], {...clamp, easing: easeMorph});
  const arr = interpolate(f, [at(2) + 12, at(2) + 30], [0, 1], {...clamp, easing: easeMorph});
  const r = interpolate(f, [at(1) + 4, at(1) + 20], [0, 1], {...clamp, easing: easeMorph});
  const qr = spring({frame: f - at(2) - 6, fps, config: T.motion.spring_pop});
  const pulse = 1 + 0.025 * Math.sin((f / fps) * Math.PI * 1.2) * interpolate(f, [at(2) + 30, at(2) + 45], [0, 1], clamp);
  const fadeOut = interpolate(f, [O.duration_s * fps - 12, O.duration_s * fps], [1, 0], clamp);
  const x0 = 150;
  return (
    <AbsoluteFill style={{opacity: fadeOut}}>
      <Stage />
      <div style={{position: 'absolute', left: x0, top: 118, fontFamily: MONO, fontWeight: 700, fontSize: 22, letterSpacing: '0.16em', color: C.coral, ...rise(0)}}>
        {O.kicker}
      </div>
      {/* two lines: one line at 84 px ran under the QR card (v1 bug, still outro_f150 08:24) */}
      <div style={{position: 'absolute', left: x0, top: 160, width: 1060, fontFamily: UI, fontWeight: 800, fontSize: 84, lineHeight: 1.06, letterSpacing: '-0.02em', color: C.ink_on_dark, ...rise(1)}}>
        {(O.headline_lines ?? [O.headline]).map((l: string, i: number) => (
          <React.Fragment key={i}>
            {i ? <br /> : null}
            {l}
          </React.Fragment>
        ))}
      </div>
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        <Draw d={markerUnderline(x0 - 4, x0 + (O.underline_w ?? 300), 362, 'o1')} p={ul} stroke={C.coral} width={8} />
        {rays(x0 + (O.underline_w ?? 300) + 50, 300, 1, 'or', 30).map((d, i) => (
          <Draw key={i} d={d} p={r} stroke={C.coral} width={5} />
        ))}
        {arrow(x0 + 900, 475, x0 + 1110, 400, 60, 'oa').map((d, i) => (
          <Draw key={`a${i}`} d={d} p={arr} stroke={C.lavender} width={4} />
        ))}
      </svg>
      {/* link chip */}
      <div
        style={{
          position: 'absolute',
          left: x0,
          top: 410,
          padding: '18px 34px',
          borderRadius: T.radius.button,
          background: C.coral,
          color: C.navy,
          fontFamily: UI,
          fontWeight: 800,
          fontSize: 64,
          letterSpacing: '-0.01em',
          boxShadow: '0 18px 40px rgba(242,105,65,0.28)',
          ...rise(2),
          transform: `${rise(2).transform} scale(${pulse})`,
          transformOrigin: 'left center',
        }}
      >
        {O.cta_link}
      </div>
      {/* next stream card */}
      <div
        style={{
          position: 'absolute',
          left: x0,
          top: 590,
          width: 900,
          padding: '26px 30px',
          borderRadius: 18,
          background: 'rgba(23,26,49,0.92)',
          outline: `1px solid ${C.bubble_edge}`,
          fontFamily: UI,
          ...rise(3),
        }}
      >
        <div style={{fontFamily: MONO, fontSize: 18, letterSpacing: '0.14em', color: C.lavender}}>{O.next_label}</div>
        <div style={{fontWeight: 800, fontSize: 48, color: C.ink_on_dark, marginTop: 10}}>
          {O.next_when} <span style={{color: C.coral}}>{O.next_time}</span>
        </div>
      </div>
      <div style={{position: 'absolute', left: x0, top: 800, fontFamily: UI, fontWeight: 600, fontSize: 34, color: C.lavender, ...rise(4)}}>
        {O.extra_label} <span style={{color: C.ink_on_dark, fontWeight: 800}}>{O.extra_value}</span>
      </div>
      {/* QR codes on paper cards */}
      <div
        style={{
          position: 'absolute',
          left: 1290,
          top: 190,
          width: 440,
          padding: 24,
          borderRadius: 24,
          background: C.paper,
          boxShadow: C.frame_shadow,
          textAlign: 'center',
          opacity: Math.min(1, qr * 1.5),
          transform: `translateY(${(1 - qr) * 30}px) rotate(${(1 - qr) * 3 + 1.2}deg)`,
        }}
      >
        {O.qr_main ? <Img src={staticFile(O.qr_main)} style={{width: 392, height: 392, display: 'block'}} /> : null}
        <div style={{fontFamily: UI, fontWeight: 800, fontSize: 28, color: C.navy, marginTop: 10}}>{O.qr_main_caption}</div>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 1290,
          top: 760,
          display: 'flex',
          alignItems: 'center',
          gap: 18,
          ...rise(4),
        }}
      >
        {O.qr_small ? (
          <div style={{padding: 10, borderRadius: 14, background: C.paper}}>
            <Img src={staticFile(O.qr_small)} style={{width: 150, height: 150, display: 'block'}} />
          </div>
        ) : null}
        <div style={{fontFamily: UI, fontWeight: 700, fontSize: 26, color: C.lavender, lineHeight: 1.3}}>
          {O.qr_small_caption?.[0]}
          <br />
          <span style={{color: C.ink_on_dark}}>{O.qr_small_caption?.[1]}</span>
        </div>
      </div>
      {BRAND.logo ? (
        <Img
          src={staticFile(BRAND.logo)}
          style={{position: 'absolute', left: x0, top: 948, height: 58, opacity: interpolate(f, [at(4) + 10, at(4) + 30], [0, 0.9], {...clamp, easing: easeEnter})}}
        />
      ) : null}
    </AbsoluteFill>
  );
};
