// Stage-level animated elements of the Program composition: poll card, reactions, doodles around
// the slide, key-phrase heroes, winner banner, confetti, chips/tags/toasts. Nothing here is ever
// placed over slide text or a demo: they live on the stage margins, the chat column or the band.
import React from 'react';
import {Easing, interpolate, random, spring} from 'remotion';
import {Draw} from '../components/Sketch';
import {easeEnter, easeExit, easeMorph} from '../components/Layout';
import {HAND, MONO, UI} from '../fonts';
import {C, Rect, T} from '../tokens';
import {handArrow, handBracket, handEllipse, handRays, handUnderline, wobble} from './hand';
import {EMOJI_TO_ICON, IconKind, SketchIcon} from './icons';
import {ConfettiSpec, Doodle, Hero, Poll, Reaction, WinnerSpec} from './types';

const cl = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const FPS = 25;

// ---------------------------------------------------------------- poll (pinned in the chat column)
export const POLL_H = (p: Poll) => 118 + p.options.length * 50;

export const pollPresence = (polls: Poll[], f: number) => {
  // 0..1 height share of the pinned poll card (spring in, ease out)
  let best = 0;
  let poll: Poll | null = null;
  for (const p of polls) {
    if (f < p.from - 1 || f > p.to + 14) continue;
    const a = spring({frame: f - p.from, fps: FPS, config: {damping: 22, stiffness: 150, mass: 0.9}});
    const b = interpolate(f, [p.to, p.to + 12], [1, 0], {...cl, easing: easeExit});
    const v = Math.min(a, b);
    if (v > best) {
      best = v;
      poll = p;
    }
  }
  return {v: best, poll};
};

export const PollCard: React.FC<{poll: Poll; f: number; rect: Rect; v: number}> = ({poll, f, rect, v}) => {
  const [x, y, w] = rect;
  const H = POLL_H(poll);
  const counts: Record<string, number> = {};
  const lastAt: Record<string, number> = {};
  for (const o of poll.options) counts[o.key] = 0;
  let total = 0;
  for (const vt of poll.votes) {
    if (vt.frame > f || counts[vt.key] === undefined) continue;
    counts[vt.key] += 1;
    lastAt[vt.key] = vt.frame;
    total += 1;
  }
  const max = Math.max(1, ...Object.values(counts));
  const lead = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0];
  const closing = f >= poll.to - 50;
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: w,
        height: H,
        opacity: Math.min(1, v * 1.6),
        // the card unrolls downwards in step with the list it pushes: it never overlaps a bubble
        clipPath: `inset(0 0 ${(1 - Math.min(1, v)) * 100}% 0 round 18px)`,
        borderRadius: 18,
        background: 'linear-gradient(180deg, #1D2046 0%, #15173A 100%)',
        outline: `2px solid ${C.coral_line}`,
        outlineOffset: -2,
        boxShadow: '0 14px 34px rgba(0,0,0,0.45)',
        padding: '16px 18px',
        boxSizing: 'border-box',
        fontFamily: UI,
        overflow: 'hidden',
      }}
    >
      <div style={{display: 'flex', alignItems: 'center', gap: 8, fontFamily: MONO, fontSize: 14, letterSpacing: '0.14em', color: C.coral}}>
        <span style={{width: 8, height: 8, borderRadius: 4, background: C.coral, opacity: Math.floor(f / 20) % 2 ? 0.35 : 1}} />
        {poll.kicker ?? 'ОПРОС В ЧАТЕ'}
        <span style={{marginLeft: 'auto', color: C.lavender, fontVariantNumeric: 'tabular-nums'}}>{total} отв.</span>
      </div>
      <div style={{color: C.ink_on_dark, fontWeight: 800, fontSize: 25, marginTop: 8, letterSpacing: '-0.01em'}}>{poll.title}</div>
      <div style={{marginTop: 12}}>
        {poll.options.map((o) => {
          const c = counts[o.key];
          const bump = lastAt[o.key] !== undefined ? spring({frame: f - lastAt[o.key], fps: FPS, config: {damping: 10, stiffness: 220, mass: 0.5}}) : 1;
          const share = c / max;
          const isLead = closing && o.key === lead && c > 0;
          return (
            <div key={o.key} style={{display: 'flex', alignItems: 'center', gap: 10, height: 50}}>
              <div
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: 17,
                  background: isLead ? C.coral : 'rgba(201,203,224,0.12)',
                  color: isLead ? C.navy : C.ink_on_dark,
                  fontWeight: 800,
                  fontSize: 19,
                  lineHeight: '34px',
                  textAlign: 'center',
                  flex: 'none',
                }}
              >
                {o.key}
              </div>
              <div style={{flex: 1, position: 'relative', height: 34}}>
                <div style={{position: 'absolute', inset: 0, borderRadius: 9, background: 'rgba(201,203,224,0.07)'}} />
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: `${Math.max(0.02, share) * 100}%`,
                    borderRadius: 9,
                    background: isLead ? C.coral : o.key === lead ? 'rgba(242,105,65,0.55)' : 'rgba(201,203,224,0.30)',
                    transition: 'none',
                  }}
                />
                <div style={{position: 'absolute', left: 10, top: 0, lineHeight: '34px', fontSize: 16, fontWeight: 600, color: C.ink_on_dark, whiteSpace: 'nowrap'}}>{o.label}</div>
              </div>
              <div
                style={{
                  width: 34,
                  textAlign: 'right',
                  fontWeight: 800,
                  fontSize: 22,
                  color: isLead ? C.coral : C.ink_on_dark,
                  fontVariantNumeric: 'tabular-nums',
                  transform: `scale(${1 + 0.35 * (1 - bump)})`,
                  transformOrigin: 'right center',
                }}
              >
                {c}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------- reactions (hand-drawn, floating)
export const Reactions: React.FC<{items: Reaction[]; f: number; origin: [number, number, number]}> = ({items, f, origin}) => {
  // origin = [x_left, x_right, y] band the icons rise from (bottom of the chat column / cam)
  const LIFE = 70;
  return (
    <>
      {items.map((r, i) => {
        const t = f - r.frame;
        if (t < 0 || t > LIFE) return null;
        const kind: IconKind = (EMOJI_TO_ICON[r.kind] ?? (r.kind as IconKind)) || 'star';
        const seed = `re${i}${r.frame}`;
        const [xa, xb, y0] = Array.isArray(r.origin) ? [r.origin[0] - 30, r.origin[0] + 30, r.origin[1]] : origin;
        const x0 = xa + (xb - xa) * random(seed + 'x');
        const pop = spring({frame: t, fps: FPS, config: {damping: 9, stiffness: 180, mass: 0.5}});
        const rise = interpolate(t, [0, LIFE], [0, 1], {...cl, easing: Easing.out(Easing.quad)});
        const sway = Math.sin(t / 7 + random(seed + 's') * 6) * 14;
        const rot = (random(seed + 'r') - 0.5) * 24 + Math.sin(t / 9) * 6;
        const fade = interpolate(t, [LIFE - 18, LIFE], [1, 0], cl) * ((r as any)._fade ?? 1);
        const size = 58 + random(seed + 'z') * 18;
        const p = interpolate(t, [0, 10], [0, 1], cl);
        const q = interpolate(t, [7, 13], [0, 1], cl);
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x0 + sway - size / 2,
              top: y0 - rise * 300 - size / 2,
              opacity: fade,
              transform: `rotate(${rot}deg) scale(${0.4 + 0.6 * pop})`,
              filter: 'drop-shadow(0 6px 10px rgba(0,0,0,0.45))',
            }}
          >
            <SketchIcon kind={kind} size={size} p={p} q={q} seed={seed} />
          </div>
        );
      })}
    </>
  );
};

// ---------------------------------------------------------------- doodles around the slide
export const Doodles: React.FC<{items: Doodle[]; f: number; mapContent: (pt: [number, number]) => [number, number]}> = ({items, f, mapContent}) => (
  <>
    <svg width={1920} height={1080} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', pointerEvents: 'none'}}>
      {items.map((d, i) => {
        if (f < d.from) return null;
        const out = d.to !== undefined ? interpolate(f, [d.to - 8, d.to], [1, 0], cl) : 1;
        if (out <= 0) return null;
        const col = d.color ?? C.coral;
        const dur = d.dur ?? 14;
        const p = interpolate(f, [d.from, d.from + dur], [0, 1], {...cl, easing: easeMorph});
        const seed = d.seed ?? `dd${i}`;
        if (d.type === 'arrow') {
          const tip = d.to_content ? mapContent(d.to_content) : d.tip ?? [d.at[0] + 100, d.at[1]];
          const [sh, hl, hr] = handArrow(d.at[0], d.at[1], tip[0], tip[1], d.bend ?? 40, seed, 22);
          return (
            <g key={i} opacity={out}>
              <Draw d={sh} p={interpolate(p, [0, 0.8], [0, 1], cl)} stroke={col} width={d.size ?? 6} />
              <Draw d={hl} p={interpolate(p, [0.78, 0.92], [0, 1], cl)} stroke={col} width={d.size ?? 6} />
              <Draw d={hr} p={interpolate(p, [0.86, 1], [0, 1], cl)} stroke={col} width={d.size ?? 6} />
            </g>
          );
        }
        if (d.type === 'bracket') {
          const tip = d.tip ?? [d.at[0], d.at[1] + 200];
          return <Draw key={i} d={handBracket(d.at[0], d.at[1], tip[1], 1, seed)} p={p} stroke={col} width={d.size ?? 5} opacity={out} />;
        }
        if (d.type === 'circle_stage') {
          const tip = d.tip ?? [120, 60];
          return <Draw key={i} d={handEllipse(d.at[0], d.at[1], tip[0], tip[1], seed)} p={p} stroke={col} width={d.size ?? 6} opacity={out} />;
        }
        if (d.type === 'stars') {
          return (
            <g key={i} opacity={out}>
              {[0, 1, 2].map((k) => {
                const a = interpolate(f, [d.from + k * 5, d.from + k * 5 + 10], [0, 1], cl);
                const tw = 1 + 0.12 * Math.sin((f - d.from) / 5 + k);
                const cx = d.at[0] + [0, 46, -34][k];
                const cy = d.at[1] + [0, -40, -52][k];
                const s = [1, 0.62, 0.48][k] * (d.size ?? 1) * tw;
                return (
                  <g key={k} transform={`translate(${cx} ${cy}) scale(${s})`}>
                    {handRays(0, 0, 1, seed + k, 18, 0).concat(handRays(0, 0, -1, seed + 'b' + k, 18, 0)).map((dd, j) => (
                      <Draw key={j} d={dd} p={a} stroke={j % 2 ? C.sketch_yellow : col} width={5} />
                    ))}
                  </g>
                );
              })}
            </g>
          );
        }
        return null;
      })}
    </svg>
    {items.map((d, i) => {
      if (f < d.from || (d.type !== 'label' && d.type !== 'stat')) return null;
      const out = d.to !== undefined ? interpolate(f, [d.to - 8, d.to], [1, 0], cl) : 1;
      if (out <= 0) return null;
      const dur = d.dur ?? 16;
      const q = interpolate(f, [d.from, d.from + dur], [0, 1], {...cl, easing: easeEnter});
      const align = d.align ?? 'left';
      const tx = align === 'center' ? '-50%' : align === 'right' ? '-100%' : '0%';
      if (d.type === 'label') {
        return (
          <div
            key={`l${i}`}
            style={{
              position: 'absolute',
              left: d.at[0],
              top: d.at[1],
              transform: `translateX(${tx}) rotate(${d.rotate ?? -3}deg)`,
              fontFamily: HAND,
              fontWeight: 700,
              fontSize: d.size ?? 46,
              lineHeight: 1.05,
              color: d.color ?? C.ink_on_dark,
              whiteSpace: 'pre',
              textAlign: align,
              clipPath: `inset(-20px ${(1 - q) * 100}% -20px -20px)`,
              opacity: out,
              textShadow: '0 3px 12px rgba(0,0,0,0.5)',
            }}
          >
            {d.text}
          </div>
        );
      }
      const cnt = interpolate(f, [d.from, d.from + 28], [0, d.value ?? 0], {...cl, easing: Easing.out(Easing.cubic)});
      const pop = spring({frame: f - d.from, fps: FPS, config: {damping: 11, stiffness: 160, mass: 0.6}});
      return (
        <div key={`s${i}`} style={{position: 'absolute', left: d.at[0], top: d.at[1], transform: `translateX(${tx}) scale(${0.7 + 0.3 * pop})`, transformOrigin: 'left top', opacity: out * Math.min(1, pop * 2), textAlign: align}}>
          <div style={{fontFamily: UI, fontWeight: 800, fontSize: d.size ?? 78, color: d.color ?? C.coral, letterSpacing: '-0.03em', lineHeight: 1, fontVariantNumeric: 'tabular-nums'}}>
            {d.prefix ?? ''}
            {Math.round(cnt).toLocaleString('ru-RU')}
            {d.suffix ?? ''}
          </div>
          {d.text ? <div style={{fontFamily: HAND, fontWeight: 700, fontSize: 36, color: C.ink_on_dark, marginTop: 4, transform: 'rotate(-2deg)'}}>{d.text}</div> : null}
        </div>
      );
    })}
  </>
);

// ---------------------------------------------------------------- key-phrase hero in the caption band
export const HeroCallout: React.FC<{h: Hero; f: number; band: {center_x: number; max_width: number; top: number; bottom: number}}> = ({h, f, band}) => {
  if (f < h.from || f >= h.to) return null;
  const q = interpolate(f, [h.from, h.from + 14], [0, 1], {...cl, easing: easeEnter});
  const out = interpolate(f, [h.to - 7, h.to], [1, 0], cl);
  const ul = interpolate(f, [h.from + 10, h.from + 24], [0, 1], {...cl, easing: easeMorph});
  const size = h.text.length > 30 ? 52 : 60;
  const w = Math.min(band.max_width, h.text.length * size * 0.56);
  const cx = band.center_x;
  const top = band.top + 6;
  const parts = h.em ? h.text.split(h.em) : [h.text];
  return (
    <div style={{position: 'absolute', left: cx - band.max_width / 2, width: band.max_width, top, textAlign: 'center', opacity: out}}>
      {h.kicker ? (
        <div style={{fontFamily: MONO, fontWeight: 700, fontSize: 15, letterSpacing: '0.18em', color: C.coral, opacity: q, marginBottom: 2}}>{h.kicker}</div>
      ) : null}
      <div
        style={{
          fontFamily: UI,
          fontWeight: 800,
          fontSize: size,
          lineHeight: 1.12,
          letterSpacing: '-0.02em',
          color: C.ink_on_dark,
          clipPath: `inset(-20px ${(1 - q) * 100}% -20px -20px)`,
          whiteSpace: 'nowrap',
        }}
      >
        {parts[0]}
        {h.em ? <span style={{color: C.coral}}>{h.em}</span> : null}
        {h.em ? parts[1] : null}
      </div>
      <svg width={band.max_width} height={24} style={{display: 'block', margin: '0 auto', overflow: 'visible'}}>
        {handUnderline(band.max_width / 2 - w / 2, band.max_width / 2 + w / 2, 6, 'hero' + h.from).map((d, i) => (
          <Draw key={i} d={d} p={interpolate(ul, [i * 0.7, i * 0.3 + 0.7], [0, 1], cl)} stroke={C.coral} width={6} />
        ))}
      </svg>
    </div>
  );
};

// ---------------------------------------------------------------- winner banner (raffle hero moment)
export const WinnerBanner: React.FC<{w: WinnerSpec; f: number; band: {center_x: number; top: number; bottom: number}}> = ({w, f, band}) => {
  if (f < w.from || f >= w.to) return null;
  const s = spring({frame: f - w.from, fps: FPS, config: {damping: 12, stiffness: 140, mass: 0.8}});
  const out = interpolate(f, [w.to - 8, w.to], [1, 0], cl);
  const name = spring({frame: f - w.from - 6, fps: FPS, config: {damping: 14, stiffness: 160, mass: 0.7}});
  const prize = spring({frame: f - w.from - 12, fps: FPS, config: {damping: 12, stiffness: 170, mass: 0.6}});
  return (
    <div
      style={{
        position: 'absolute',
        left: band.center_x,
        top: band.top + 6,
        transform: `translateX(-50%) scale(${0.6 + 0.4 * s})`,
        transformOrigin: 'center top',
        opacity: out * Math.min(1, s * 1.5),
        display: 'flex',
        alignItems: 'center',
        gap: 22,
        padding: '10px 26px 10px 18px',
        borderRadius: 22,
        background: 'linear-gradient(180deg, #1D2046, #12143A)',
        outline: `2px solid ${C.coral}`,
        outlineOffset: -2,
        boxShadow: '0 0 0 8px rgba(242,105,65,0.14), 0 18px 40px rgba(0,0,0,0.5)',
        whiteSpace: 'nowrap',
      }}
    >
      <SketchIcon kind="party" size={64} p={interpolate(f - w.from, [0, 12], [0, 1], cl)} q={interpolate(f - w.from, [8, 14], [0, 1], cl)} seed={'w' + w.from} />
      <div>
        <div style={{fontFamily: MONO, fontWeight: 700, fontSize: 15, letterSpacing: '0.18em', color: C.coral}}>{w.kicker}</div>
        <div style={{fontFamily: UI, fontWeight: 800, fontSize: 44, color: C.ink_on_dark, letterSpacing: '-0.02em', lineHeight: 1.05, opacity: name, transform: `translateY(${(1 - name) * 10}px)`}}>{w.name}</div>
      </div>
      <div
        style={{
          fontFamily: UI,
          fontWeight: 800,
          fontSize: 24,
          color: C.navy,
          background: C.coral,
          borderRadius: 14,
          padding: '8px 16px',
          transform: `scale(${prize})`,
        }}
      >
        {w.prize}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------- confetti (paper bits + sketch squiggles)
const CONF_COLORS = ['#F26941', '#FFD014', '#C9CBE0', '#F4F1EA', '#F29BB8'];
export const Confetti: React.FC<{c: ConfettiSpec; f: number}> = ({c, f}) => {
  const t = f - c.frame;
  const LIFE = 84;
  if (t < 0 || t > LIFE) return null;
  const n = c.count ?? 90;
  const seed = c.seed ?? `cf${c.frame}`;
  return (
    <svg width={1920} height={1080} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', pointerEvents: 'none'}}>
      {Array.from({length: n}).map((_, i) => {
        const a = -Math.PI / 2 + (random(`${seed}a${i}`) - 0.5) * (c.spread ?? 2.4);
        const v = 16 + random(`${seed}v${i}`) * 22;
        const drag = 0.955;
        const k = (1 - Math.pow(drag, t)) / (1 - drag);
        const x = c.origin[0] + Math.cos(a) * v * k + Math.sin(t / 6 + i) * 6;
        const y = c.origin[1] + Math.sin(a) * v * k + 0.34 * t * t * 0.5;
        const rot = random(`${seed}r${i}`) * 360 + t * (random(`${seed}w${i}`) - 0.5) * 30;
        const col = CONF_COLORS[i % CONF_COLORS.length];
        const op = interpolate(t, [0, 3, LIFE - 22, LIFE], [0, 1, 1, 0], cl);
        const kind = i % 4;
        return (
          <g key={i} transform={`translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${rot.toFixed(1)})`} opacity={op}>
            {kind === 0 ? <rect x={-7} y={-4} width={14} height={8} rx={1.5} fill={col} /> : null}
            {kind === 1 ? <path d={wobble([[-10, 0], [-3, -5], [4, 4], [11, -1]], `${seed}q${i}`, 1)} stroke={col} strokeWidth={3.5} fill="none" strokeLinecap="round" /> : null}
            {kind === 2 ? <circle r={4.5} fill={col} /> : null}
            {kind === 3 ? <path d="M0 -8 L2.4 -2.4 L8 0 L2.4 2.4 L0 8 L-2.4 2.4 L-8 0 L-2.4 -2.4 Z" fill={col} /> : null}
          </g>
        );
      })}
    </svg>
  );
};

// ---------------------------------------------------------------- small pills
export const Pill: React.FC<{text: string; f: number; from: number; to: number; at: [number, number]; coral?: boolean}> = ({text, f, from, to, at, coral}) => {
  if (f < from || f >= to) return null;
  const s = spring({frame: f - from, fps: FPS, config: T.motion.spring_plate});
  const out = interpolate(f, [to - 6, to], [1, 0], cl);
  return (
    <div
      style={{
        position: 'absolute',
        left: at[0],
        top: at[1],
        padding: coral ? '8px 16px' : '8px 14px',
        borderRadius: coral ? 18 : 10,
        background: coral ? C.coral : 'rgba(1,3,52,0.86)',
        color: coral ? C.navy : C.coral,
        fontFamily: coral ? UI : MONO,
        fontWeight: coral ? 800 : 700,
        fontSize: coral ? 20 : 17,
        letterSpacing: coral ? '0.02em' : '0.14em',
        opacity: out * s,
        transform: `translateY(${(1 - s) * -10}px)`,
        whiteSpace: 'nowrap',
        boxShadow: '0 8px 20px rgba(0,0,0,0.35)',
      }}
    >
      {text}
    </div>
  );
};
