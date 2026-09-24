import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, cancelRender, continueRender, delayRender, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {BUTTON, CAPTION, CORAL, DARK, FACE, FPS, INK, LOGO, MUTED, MUTED_DARK, PANEL, PAPER, TRACKER} from './design';
import {Sheet, SketchArt} from './SketchArt';

export type Word = {w: string; s: number; e: number};
export type Step = {n: number; label: string; active: [number, number]; spot: [number, number]; target: [number, number, number, number]};
export type PanelSketch = {art: string; start: number; end: number; draw: number};
// Zoom rect in fractions of the raw screen frame; outside every zoom the whole frame is shown.
export type Zoom = {start: number; end: number; rect: [number, number, number, number]};
// Privacy blur: rect in raw-frame fractions (process: mapped through the active zoom; result: result-frame fractions),
// times on the story clock.
export type Blur = {start: number; end: number; rect: [number, number, number, number]};
// Webinar-story additions (all optional, the b5_01 case clip renders exactly as before):
// callouts — timed overlays over the panel: anonymous chat bubbles, a hand-drawn vote tally, count-up stats, a coral note.
export type ChatMsg = string | {text: string; hi?: boolean};
export type Callout =
  // chat: lift = px to raise the bubble stack's bottom row (clear a prompt line at the slide bottom), max = bubbles on screen (default 5)
  | {type: 'chat'; start: number; end: number; title?: string; messages: ChatMsg[]; every?: number; lift?: number; max?: number}
  | {type: 'tally'; start: number; end: number; title: string; bars: {label: string; value: number; hi?: boolean}[]; note?: string}
  | {type: 'stat'; start: number; end: number; title?: string; items: {value: number; label: string; prefix?: string; suffix?: string; hi?: boolean}[]; note?: string}
  | {type: 'note'; start: number; end: number; text: string; x: number; y: number; arrow?: 'left' | 'right' | 'up' | 'down'};
export type FaceLabel = {start: number; end: number; text: string};
export type StoryProps = {
  dir: string; fps: number; frames: number; eyebrow: string; title: string;
  hook: {end: number; title: string; art: string};
  process: {screen: string; face?: string; dur: number; zooms?: Zoom[]; blurs?: Blur[]; faceLabels?: FaceLabel[]};
  // result is optional: an idea story has no "result" segment; title/stamp default to the case-clip wording
  // stampInTitle: put the stamp on the title row instead of the panel corner (when the result screen has text in its top corners)
  result?: {screen: string; face?: string; start: number; dur: number; blurs?: Blur[]; title?: string; stamp?: string; stampInTitle?: boolean; zooms?: Zoom[]};
  steps: Step[]; sketches: PanelSketch[];
  cta: {start: number; title: string; items: string[]; button: string; bot: string};
  button: string; words: Word[];
  doneText?: string;          // tracker text during the result segment
  callouts?: Callout[];
  cuts?: number[];            // story-clock times of jump cuts: the face circle alternates framing so cuts read as intentional
};

const ease = (f: number, a: number, b: number, from = 0, to = 1) =>
  interpolate(f, [a, b], [from, to], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
const sec = (s: number) => Math.round(s * FPS);

function Logo({dark = false}: {dark?: boolean}) {
  return <Img src={staticFile(`common/logo-${dark ? 'dark' : 'light'}.svg`)}
    style={{position: 'absolute', left: LOGO.x, top: LOGO.y, width: LOGO.w, height: LOGO.h, objectFit: 'contain', objectPosition: 'left'}}/>;
}

function Underline({x = 96, y, width, start = 6, color = CORAL}: {x?: number; y: number; width: number; start?: number; color?: string}) {
  const f = useCurrentFrame();
  return <svg width="1080" height="1920" style={{position: 'absolute', inset: 0}}>
    <path d={`M${x} ${y} Q${x + width * .55} ${y - 14} ${x + width} ${y + 1}`} fill="none" stroke={color} strokeWidth="12"
      strokeLinecap="round" pathLength="1" strokeDasharray="1" strokeDashoffset={1 - ease(f, start, start + 16)}/>
  </svg>;
}

function Lines({text, top, size, color, left = 94, weight = 'Heading'}: {text: string; top: number; size: number; color: string; left?: number; weight?: string}) {
  return <div style={{position: 'absolute', left, right: 70, top, fontFamily: weight, fontSize: size, lineHeight: 1.06, letterSpacing: -1.5, color, whiteSpace: 'pre-line'}}>{text}</div>;
}

function Appear({children, start, top, size, color, bold = false, left = 96, width = 888, align = 'left'}: {
  children: React.ReactNode; start: number; top: number; size: number; color: string; bold?: boolean; left?: number; width?: number; align?: 'left' | 'center';
}) {
  const f = useCurrentFrame();
  return <div style={{position: 'absolute', left, top, width, fontSize: size, lineHeight: 1.2, textAlign: align, color,
    fontFamily: bold ? 'Heading' : 'Body', opacity: ease(f, start, start + 9), translate: `0 ${ease(f, start, start + 9, 14, 0)}px`}}>{children}</div>;
}

// Hand-drawn rectangle: slightly uneven corners so it reads as a marker, not a UI frame.
function roughRect(x: number, y: number, w: number, h: number) {
  const j = (k: number) => (Math.sin(k * 12.9898) * 43758.5453) % 1 * 5;
  return `M${x + 10 + j(1)} ${y + j(2)} L${x + w - 8 + j(3)} ${y - 3 + j(4)} Q${x + w + 4} ${y + 2} ${x + w + 2 + j(5)} ${y + 12}`
    + ` L${x + w + 5 + j(6)} ${y + h - 10} Q${x + w + 2} ${y + h + 4} ${x + w - 12} ${y + h + 3 + j(7)}`
    + ` L${x + 8 + j(8)} ${y + h + 4} Q${x - 5} ${y + h} ${x - 4 + j(9)} ${y + h - 12} L${x - 6 + j(10)} ${y + 14}`
    + ` Q${x - 3} ${y - 2} ${x + 22} ${y + 1}`;
}

const zoomAt = (zooms: Zoom[] | undefined, t: number) => zooms?.find(z => t >= z.start && t < z.end)?.rect ?? [0, 0, 1, 1];

function Screen({src, zooms, from = 0}: {src: string; zooms?: Zoom[]; from?: number}) {
  const t = useCurrentFrame() / FPS + from;          // zoom times are on the story clock
  const [x, y, w] = zoomAt(zooms, t);
  const s = 1 / w;
  return <div style={{position: 'absolute', inset: 0, overflow: 'hidden'}}>
    <OffthreadVideo muted src={staticFile(src)} style={{position: 'absolute', left: 0, top: 0, width: '100%', height: '100%', objectFit: 'cover',
      transformOrigin: '0 0', transform: `scale(${s}) translate(${-x * 100}%, ${-y * 100}%)`}}/>
  </div>;
}


function Blurs({list, zooms}: {list?: Blur[]; zooms?: Zoom[]}) {
  const t = useCurrentFrame() / FPS;
  const on = (list || []).filter(b => t >= b.start && t < b.end);
  if (!on.length) return null;
  const [zx, zy, zw, zh] = zoomAt(zooms, t);
  return <>{on.map((b, i) => {
    const x = PANEL.x + (b.rect[0] - zx) / zw * PANEL.w, y = PANEL.y + (b.rect[1] - zy) / zh * PANEL.h;
    const w = b.rect[2] / zw * PANEL.w, h = b.rect[3] / zh * PANEL.h;
    return <div key={i} style={{position: 'absolute', left: x - 6, top: y - 6, width: w + 12, height: h + 12, borderRadius: 10,
      backdropFilter: 'blur(18px)', background: 'rgba(248,243,236,.25)', clipPath: `inset(${Math.max(0, PANEL.y - y + 6)}px 0 0 0)`}}/>;
  })}</>;
}

function Spotlight({step, zooms}: {step: Step; zooms?: Zoom[]}) {
  const f = useCurrentFrame();                       // local: 0 at spot start
  const dur = sec(step.spot[1] - step.spot[0]);
  const on = Math.min(ease(f, 0, 7), ease(f, dur - 7, dur, 1, 0));
  const pad = 12;
  const [zx, zy, zw, zh] = zoomAt(zooms, step.spot[0] + f / FPS);  // target is in raw-frame fractions; map through the zoom
  const fx = (step.target[0] - zx) / zw, fy = (step.target[1] - zy) / zh, fw = step.target[2] / zw, fh = step.target[3] / zh;
  const tx = PANEL.x + fx * PANEL.w - pad, ty = PANEL.y + fy * PANEL.h - pad;
  const tw = fw * PANEL.w + 2 * pad, th = fh * PANEL.h + 2 * pad;
  const id = `spot-${step.n}`;
  return <svg width="1080" height="1920" style={{position: 'absolute', inset: 0, opacity: on}}>
    <defs>
      <clipPath id={`${id}-panel`}><rect x={PANEL.x} y={PANEL.y} width={PANEL.w} height={PANEL.h} rx={PANEL.r}/></clipPath>
      <mask id={`${id}-hole`}><rect x={0} y={0} width={1080} height={1920} fill="white"/><rect x={tx} y={ty} width={tw} height={th} rx={14} fill="black"/></mask>
    </defs>
    <rect x={PANEL.x} y={PANEL.y} width={PANEL.w} height={PANEL.h} fill={INK} opacity={.42} mask={`url(#${id}-hole)`} clipPath={`url(#${id}-panel)`}/>
    <path d={roughRect(tx, ty, tw, th)} fill="none" stroke={CORAL} strokeWidth={8} strokeLinecap="round" strokeLinejoin="round"
      pathLength={1} strokeDasharray={1} strokeDashoffset={1 - ease(f, 2, 18)}/>
    <g transform={`translate(${Math.max(PANEL.x + 34, tx)} ${Math.max(PANEL.y + 34, ty)}) scale(${ease(f, 12, 20, .4, 1)})`} opacity={ease(f, 12, 16)}>
      <circle r={32} fill={CORAL}/>
      <text y={12} textAnchor="middle" fontFamily="Heading" fontSize={36} fill={INK}>{step.n}</text>
    </g>
  </svg>;
}

// One large pill that says what is happening right now: progress dots + "Шаг 2 из 3 · <label>".
function Tracker({steps, t}: {steps: Step[]; t: number}) {
  const cur = steps.find(s => t >= s.active[0] && t < s.active[1]);
  const since = cur ? t - cur.active[0] : 0;
  const pop = cur ? interpolate(since, [0, .25], [1.06, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 1;
  return <div style={{position: 'absolute', left: TRACKER.x, top: TRACKER.y, width: TRACKER.w, height: TRACKER.h, borderRadius: TRACKER.h / 2,
    boxSizing: 'border-box', display: 'flex', alignItems: 'center', gap: 22, padding: '0 30px', transform: `scale(${pop})`,
    background: cur ? CORAL : 'transparent', border: cur ? 'none' : '3px solid #D6D0C7', color: cur ? INK : '#8F8993', fontFamily: 'Heading'}}>
    <div style={{display: 'flex', gap: 10, flex: '0 0 auto'}}>
      {steps.map(s => {
        const done = t >= s.active[1], on = s === cur;
        return <span key={s.n} style={{width: 44, height: 44, borderRadius: 22, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 25,
          background: on ? INK : done ? INK : 'transparent', color: on ? CORAL : done ? CORAL : (cur ? INK : '#8F8993'),
          border: on || done ? 'none' : `3px solid ${cur ? INK : '#D6D0C7'}`, boxSizing: 'border-box'}}>{done ? '✓' : s.n}</span>;
      })}
    </div>
    <div style={{fontSize: cur && cur.label.length > 18 ? 34 : 38, lineHeight: 1.05, whiteSpace: 'nowrap', overflow: 'hidden'}}>
      {cur ? <><span style={{opacity: .7}}>Шаг {cur.n} из {steps.length} · </span>{cur.label}</> : `${steps.length} шага — смотрите по порядку`}
    </div>
  </div>;
}

type Chunk = {s: number; end: number; words: Word[]};
function chunks(words: Word[]): Chunk[] {
  const out: Chunk[] = [];
  let cur: Word[] = [];
  const flush = () => { if (cur.length) out.push({s: cur[0].s, end: cur[cur.length - 1].e, words: cur}); cur = []; };
  words.forEach((w, i) => {
    const prev = words[i - 1];
    const chars = cur.reduce((a, x) => a + x.w.length + 1, 0);
    if (cur.length && (w.s - prev.e > .35 || cur.length >= 7 || chars + w.w.length > 36 || /[.!?…]$/.test(prev.w))) flush();
    cur.push(w);
  });
  flush();
  return out;
}

function Captions({list, t, dark = false}: {list: Chunk[]; t: number; dark?: boolean}) {
  const i = list.findIndex((c, k) => t >= c.s - .05 && t < (list[k + 1]?.s ?? c.end + .6));
  if (i < 0) return null;
  const c = list[i];
  return <div style={{position: 'absolute', left: CAPTION.x, top: CAPTION.y, width: CAPTION.w, fontFamily: 'Heading', fontSize: 50, lineHeight: 1.16,
    color: dark ? PAPER : INK}}>
    {c.words.map((w, k) => {
      const on = t >= w.s && t < w.e + .05;
      return <span key={k} style={{color: on ? CORAL : t < w.s ? (dark ? '#8C8790' : '#A8A2AA') : undefined}}>{w.w} </span>;
    })}
  </div>;
}

function Panel({children, shadow = true}: {children: React.ReactNode; shadow?: boolean}) {
  return <div style={{position: 'absolute', left: PANEL.x, top: PANEL.y, width: PANEL.w, height: PANEL.h, borderRadius: PANEL.r, overflow: 'hidden',
    boxShadow: shadow ? '0 18px 40px rgba(1,3,52,.16), 0 0 0 2px rgba(1,3,52,.10)' : undefined, background: PAPER}}>{children}</div>;
}

function Face({src, cuts, from = 0}: {src: string; cuts?: number[]; from?: number}) {
  const t = useCurrentFrame() / FPS + from;
  const k = (cuts || []).filter(c => c <= t + 1e-3).length;   // alternate framing between jump cuts
  const s = k % 2 ? 1.14 : 1;
  return <div style={{position: 'absolute', left: FACE.x, top: FACE.y, width: FACE.d, height: FACE.d, borderRadius: '50%', overflow: 'hidden',
    boxShadow: `0 0 0 8px ${CORAL}, 0 12px 30px rgba(1,3,52,.25)`}}>
    <OffthreadVideo muted src={staticFile(src)} style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${s})`, transformOrigin: '50% 42%'}}/>
  </div>;
}

function FaceTag({list, t}: {list?: FaceLabel[]; t: number}) {
  const cur = (list || []).find(l => t >= l.start && t < l.end);
  if (!cur) return null;
  return <div style={{position: 'absolute', left: FACE.x - 20, width: FACE.d + 40, top: FACE.y + FACE.d + 16, display: 'flex', justifyContent: 'center'}}>
    <span style={{background: INK, color: PAPER, fontFamily: 'Heading', fontSize: 28, padding: '6px 18px', borderRadius: 22}}>{cur.text}</span>
  </div>;
}

// ---- callouts: drawn in the same paper/ink/coral language as the rest of the story ----
const msgOf = (m: ChatMsg) => typeof m === 'string' ? {text: m, hi: false} : {text: m.text, hi: !!m.hi};

function ChatBurst({c}: {c: Extract<Callout, {type: 'chat'}>}) {
  const f = useCurrentFrame();
  const every = sec(c.every ?? .45);
  const shown = c.messages.map(msgOf).map((m, i) => ({...m, at: 6 + i * every})).filter(m => f >= m.at);
  const last = shown.slice(-(c.max ?? 5));
  const lift = c.lift ?? 0;
  const dur = sec(c.end - c.start);
  const out = ease(f, dur - 8, dur, 1, 0);
  const w = 470, x = PANEL.x + PANEL.w - w - 22;
  return <div style={{position: 'absolute', inset: 0, opacity: out}}>
    <div style={{position: 'absolute', left: x, top: PANEL.y + 20, width: w, display: 'flex', justifyContent: 'flex-end'}}>
      <span style={{background: INK, color: PAPER, fontFamily: 'Heading', fontSize: 26, padding: '6px 16px', borderRadius: 18, opacity: ease(f, 0, 6)}}>
        {c.title ?? 'Чат эфира'}</span>
    </div>
    <div style={{position: 'absolute', left: x, width: w, top: PANEL.y + 74, height: PANEL.h - 96 - lift, display: 'flex', flexDirection: 'column',
      justifyContent: 'flex-end', alignItems: 'flex-end', gap: 12}}>
      {last.map((m, i) => {
        const age = f - m.at;
        return <div key={m.at} style={{maxWidth: w, padding: '14px 26px', borderRadius: '26px 26px 6px 26px', fontFamily: m.hi ? 'Heading' : 'Body', fontSize: 40,
          lineHeight: 1.15, background: m.hi ? CORAL : PAPER, color: INK, boxShadow: '0 8px 20px rgba(1,3,52,.28)',
          border: m.hi ? 'none' : '2px solid rgba(1,3,52,.18)', opacity: ease(age, 0, 5), scale: `${ease(age, 0, 7, .7, 1)}`, transformOrigin: '100% 100%'}}
          data-i={i}>{m.text}</div>;
      })}
    </div>
  </div>;
}

function Card({children, dur}: {children: React.ReactNode; dur: number}) {
  const f = useCurrentFrame();
  const on = Math.min(ease(f, 0, 8), ease(f, dur - 8, dur, 1, 0));
  const x = PANEL.x + 46, y = PANEL.y + 40, w = PANEL.w - 92, h = PANEL.h - 80;
  return <div style={{position: 'absolute', inset: 0, opacity: on}}>
    <div style={{position: 'absolute', left: PANEL.x, top: PANEL.y, width: PANEL.w, height: PANEL.h, borderRadius: PANEL.r, background: 'rgba(1,3,52,.35)'}}/>
    <div style={{position: 'absolute', left: x, top: y, width: w, height: h, borderRadius: 22, background: PAPER, boxShadow: '0 18px 40px rgba(1,3,52,.3)',
      scale: `${ease(f, 0, 9, .94, 1)}`}}>{children}</div>
    <svg width="1080" height="1920" style={{position: 'absolute', inset: 0}}>
      <path d={roughRect(x + 10, y + 10, w - 20, h - 20)} fill="none" stroke={CORAL} strokeWidth={6} strokeLinecap="round" strokeLinejoin="round"
        pathLength={1} strokeDasharray={1} strokeDashoffset={1 - ease(f, 3, 20)}/>
    </svg>
  </div>;
}

const fmt = (v: number) => Math.round(v).toLocaleString('ru-RU').replace(/ /g, ' ');

function Tally({c}: {c: Extract<Callout, {type: 'tally'}>}) {
  const f = useCurrentFrame();
  const dur = sec(c.end - c.start);
  const max = Math.max(...c.bars.map(b => b.value), 1);
  return <Card dur={dur}>
    <div style={{position: 'absolute', left: 48, right: 48, top: 36, fontFamily: 'Heading', fontSize: 42, lineHeight: 1.1, color: INK}}>{c.title}</div>
    {c.bars.map((b, i) => {
      const s = 10 + i * 8, v = ease(f, s, s + 22) * b.value;
      return <div key={i} style={{position: 'absolute', left: 48, right: 48, top: 130 + i * 92, height: 72, display: 'flex', alignItems: 'center', gap: 20}}>
        <div style={{width: 250, fontFamily: b.hi ? 'Heading' : 'Body', fontSize: 34, color: INK}}>{b.label}</div>
        <div style={{flex: 1, height: 52, position: 'relative'}}>
          <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: `${v / max * 100}%`, borderRadius: 12,
            background: b.hi ? `repeating-linear-gradient(-55deg, ${CORAL} 0 14px, #F58A6A 14px 22px)` : `repeating-linear-gradient(-55deg, ${INK} 0 3px, transparent 3px 12px)`,
            border: b.hi ? 'none' : `3px solid ${INK}`, boxSizing: 'border-box'}}/>
        </div>
        <div style={{width: 90, textAlign: 'right', fontFamily: 'Heading', fontSize: 50, color: b.hi ? CORAL : INK}}>{fmt(v)}</div>
      </div>;
    })}
    {c.note && <div style={{position: 'absolute', left: 48, right: 48, bottom: 30, fontFamily: 'Heading', fontSize: 34, color: CORAL, opacity: ease(f, 36, 44)}}>{c.note}</div>}
  </Card>;
}

function Stats({c}: {c: Extract<Callout, {type: 'stat'}>}) {
  const f = useCurrentFrame();
  const dur = sec(c.end - c.start);
  const n = c.items.length;
  return <Card dur={dur}>
    {c.title && <div style={{position: 'absolute', left: 48, right: 48, top: 36, fontFamily: 'Heading', fontSize: 40, color: INK}}>{c.title}</div>}
    <div style={{position: 'absolute', left: 30, right: 30, top: c.title ? 130 : 90, display: 'flex', justifyContent: 'space-around'}}>
      {c.items.map((it, i) => {
        const s = 8 + i * 10;
        return <div key={i} style={{width: `${100 / n}%`, textAlign: 'center', opacity: ease(f, s, s + 6), translate: `0 ${ease(f, s, s + 8, 18, 0)}px`}}>
          <div style={{fontFamily: 'Heading', fontSize: n > 2 ? 92 : 110, letterSpacing: -2, lineHeight: 1, color: it.hi ? CORAL : INK}}>
            {it.prefix ?? ''}{fmt(ease(f, s, s + 24) * it.value)}{it.suffix ?? ''}</div>
          <div style={{fontFamily: 'Body', fontSize: 32, color: MUTED, marginTop: 12}}>{it.label}</div>
        </div>;
      })}
    </div>
    {c.note && <div style={{position: 'absolute', left: 48, right: 48, bottom: 34, textAlign: 'center', fontFamily: 'Heading', fontSize: 36, color: INK,
      opacity: ease(f, 8 + n * 10 + 10, 8 + n * 10 + 18)}}>{c.note}</div>}
  </Card>;
}

function Note({c}: {c: Extract<Callout, {type: 'note'}>}) {
  const f = useCurrentFrame();
  const dur = sec(c.end - c.start);
  const on = Math.min(ease(f, 0, 6), ease(f, dur - 6, dur, 1, 0));
  const a = c.arrow;
  const d = a === 'left' ? `M${c.x - 14} ${c.y + 30} q-60 10 -110 -30` : a === 'right' ? `M${c.x + 14} ${c.y + 30} q60 10 110 -30`
    : a === 'up' ? `M${c.x} ${c.y - 8} q-10 -50 30 -100` : a === 'down' ? `M${c.x} ${c.y + 70} q10 50 -30 100` : '';
  return <div style={{position: 'absolute', inset: 0, opacity: on}}>
    <div style={{position: 'absolute', left: c.x, top: c.y, translate: '-50% 0', whiteSpace: 'nowrap', padding: '10px 22px', borderRadius: 16, background: CORAL,
      color: INK, fontFamily: 'Heading', fontSize: 40, rotate: '-2deg', scale: `${ease(f, 0, 8, .6, 1)}`, boxShadow: '0 10px 24px rgba(1,3,52,.3)'}}>{c.text}</div>
    {d && <svg width="1080" height="1920" style={{position: 'absolute', inset: 0}}>
      <path d={d} fill="none" stroke={CORAL} strokeWidth={8} strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - ease(f, 6, 16)}/>
    </svg>}
  </div>;
}

function CalloutView({c}: {c: Callout}) {
  if (c.type === 'chat') return <ChatBurst c={c}/>;
  if (c.type === 'tally') return <Tally c={c}/>;
  if (c.type === 'stat') return <Stats c={c}/>;
  return <Note c={c}/>;
}


function TgIcon({size = 40}: {size?: number}) {
  return <svg width={size} height={size} viewBox="0 0 240 240" style={{flex: '0 0 auto'}}>
    <circle cx="120" cy="120" r="120" fill="#2AABEE"/>
    <path d="M54 118 L170 73 Q180 70 178 81 L158 172 Q155 182 145 176 L113 152 L97 167 Q92 171 91 164 L93 140 L152 87 Q156 83 150 85 L78 131 L50 122 Q42 119 54 118 Z" fill="#FFFFFF"/>
  </svg>;
}

function Button({text, fill = true, dark = false}: {text: string; fill?: boolean; dark?: boolean}) {
  return <div style={{position: 'absolute', left: BUTTON.x, top: BUTTON.y, width: BUTTON.w, height: BUTTON.h, borderRadius: 18, boxSizing: 'border-box',
    background: fill ? CORAL : 'transparent', border: fill ? 'none' : `4px solid ${CORAL}`, color: fill ? INK : (dark ? PAPER : INK),
    fontFamily: 'Heading', fontSize: text.length > 30 ? 40 : 44, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>{text}</div>;
}

function ResultStamp({text = 'РЕЗУЛЬТАТ', inTitle = false}: {text?: string; inTitle?: boolean}) {
  const f = useCurrentFrame();
  // default: stamp in the panel's top-left corner, tick in its top-right; inTitle: both right-aligned on the one-line title row (y 304..374)
  const pos = inTitle ? {right: 1080 - (PANEL.x + PANEL.w) + 130, top: 300} : {left: PANEL.x + 26, top: PANEL.y + 24};
  const tick = inTitle ? `M${PANEL.x + PANEL.w - 100} 340 l30 30 l60 -70` : `M${PANEL.x + PANEL.w - 130} ${PANEL.y + 70} l30 30 l60 -70`;
  return <>
    <div style={{position: 'absolute', ...pos, padding: '12px 26px', borderRadius: 14, background: CORAL, color: INK,
      fontFamily: 'Heading', fontSize: 38, letterSpacing: 3, rotate: '-3deg', opacity: ease(f, 4, 10), scale: `${ease(f, 4, 12, 1.25, 1)}`}}>{text}</div>
    <svg width="1080" height="1920" style={{position: 'absolute', inset: 0}}>
      <path d={tick} fill="none" stroke={CORAL} strokeWidth={16} strokeLinecap="round"
        strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - ease(f, 10, 24)}/>
    </svg>
  </>;
}

function Hook({p, sheet}: {p: StoryProps; sheet: Sheet}) {
  const f = useCurrentFrame();
  const end = sec(p.hook.end);
  const out = ease(f, end - 9, end, 1, 0);
  return <AbsoluteFill style={{background: PAPER, opacity: out}}>
    <Logo/>
    <div style={{position: 'absolute', left: 96, top: 284, display: 'flex', gap: 16, alignItems: 'center', color: CORAL, fontFamily: 'Heading', fontSize: 40, letterSpacing: 1}}>
      <span style={{width: 18, height: 18, borderRadius: 9, background: CORAL}}/>{p.eyebrow.toUpperCase()}
    </div>
    <Lines text={p.hook.title} top={372} size={96} color={INK}/>
    <Underline y={590} width={800} start={4}/>
    <SketchArt sheet={sheet} base={p.dir} id="hook" x={72} y={640} w={936} h={860} start={6} duration={Math.max(40, end - 22)} pen/>
  </AbsoluteFill>;
}

function PanelSketch({s, sheet, dir}: {s: PanelSketch; sheet: Sheet; dir: string}) {
  const f = useCurrentFrame();
  const dur = sec(s.end - s.start);
  const on = Math.min(ease(f, 0, 7), ease(f, dur - 7, dur, 1, 0));
  return <div style={{position: 'absolute', inset: 0, opacity: on}}>
    <Panel><div style={{position: 'absolute', inset: 0, background: PAPER}}/></Panel>
    <SketchArt sheet={sheet} base={dir} id={`panel-${s.art}`} x={PANEL.x + 18} y={PANEL.y + 14} w={PANEL.w - 36} h={PANEL.h - 28} start={3} duration={sec(s.draw)} pen/>
  </div>;
}

function Cta({p, sheet}: {p: StoryProps; sheet: Sheet}) {
  const f = useCurrentFrame();
  // willChange keeps the CTA on its own layer for its whole life, so reaching opacity 1 does not re-raster it
  return <AbsoluteFill style={{background: DARK, opacity: ease(f, 0, 8), willChange: 'opacity'}}>
    <Logo dark/>
    <Lines text={p.cta.title} top={300} size={90} color={PAPER}/>
    <Underline y={512} width={760} start={6}/>
    <SketchArt sheet={sheet} base="common/" id="bot" x={170} y={560} w={740} h={700} start={4} duration={62} pen/>
    {p.cta.items.map((it, i) => <Appear key={i} start={40 + i * 10} top={1290 + i * 72} size={40} color={PAPER}>
      <span style={{color: CORAL, fontFamily: 'Heading'}}>● </span>{it}</Appear>)}
    <div style={{opacity: ease(f, 62, 70), scale: `${1 + .02 * Math.sin(f / 7)}`}}><Button text={p.cta.button}/></div>
    <Appear start={30} top={1196} size={44} bold color={PAPER}><span style={{display: 'inline-flex', gap: 16, alignItems: 'center'}}><TgIcon size={52}/>Бесплатный бот в Telegram</span></Appear>
    <Appear start={70} top={1700} size={44} bold color={PAPER} align="center">{p.cta.bot}</Appear>
  </AbsoluteFill>;
}

const decoded: HTMLImageElement[] = [];   // keeps the preloaded art images alive for the tab's lifetime

export function StoryV3(p: StoryProps) {
  const f = useCurrentFrame();
  const t = f / FPS;
  const [sheets, setSheets] = useState<Record<string, Sheet> | null>(null);
  const [handle] = useState(() => delayRender('Load fonts and sketch traces'));
  useEffect(() => {
    const fonts = [new FontFace('Body', `url(${staticFile('fonts/Manrope-Regular.ttf')})`), new FontFace('Heading', `url(${staticFile('fonts/Manrope-Bold.ttf')})`)];
    const names = [p.hook.art, ...p.sketches.map(s => s.art)];
    const load = (url: string) => fetch(staticFile(url)).then(r => { if (!r.ok) throw Error('Missing ' + url); return r.json(); });
    Promise.all([Promise.all(names.map(n => load(`${p.dir}${n}.traces.json`))), load('common/art-bot.traces.json'),
      ...fonts.map(x => x.load().then(g => document.fonts.add(g)))])
      .then(([arts, bot]) => {
        const map: Record<string, Sheet> = {bot: bot as Sheet};
        (arts as Sheet[]).forEach((s, i) => { map[names[i]] = s; });
        // The art is drawn by an SVG <image>, which Remotion does not wait for: decode every sheet PNG before the
        // first frame, otherwise a busy render tab can screenshot a frame with the strokes missing (1-frame flash).
        const urls = [...(arts as Sheet[]).map(s => staticFile(p.dir + s.source)), staticFile('common/' + (bot as Sheet).source)];
        return Promise.all(urls.map(u => new Promise<void>((ok, bad) => {
          const im = new Image();
          decoded.push(im);
          im.onload = () => { im.decode().catch(() => undefined).then(() => ok()); };
          im.onerror = () => bad(Error('Missing ' + u));
          im.src = u;
        }))).then(() => { setSheets(map); continueRender(handle); });
      }).catch(cancelRender);
  }, [handle, p]);
  if (!sheets) return null;
  const list = chunks(p.words);
  const r = p.result;
  const pf = sec(p.process.dur), cs = sec(p.cta.start);
  // The CTA fades in over its first 8 frames; until it is opaque the layer below keeps its pre-CTA state
  // (title, tracker, button), otherwise the process title and step tracker flash through the fade.
  const beforeCta = f < cs + 8;
  const inResult = !!r && t >= r.start && beforeCta;
  const rs = r ? sec(r.start) : cs, rf = r ? sec(r.dur) : 0;
  return <AbsoluteFill style={{background: PAPER, fontFamily: 'Body'}}>
    <Audio src={staticFile(p.dir + 'voice.wav')}/>
    <Logo/>
    <div style={{position: 'absolute', left: 96, top: 262, color: CORAL, fontFamily: 'Heading', fontSize: 30, letterSpacing: 2}}>{p.eyebrow.toUpperCase()}</div>
    <Lines text={inResult ? (r?.title ?? 'И вот результат') : p.title} top={304} size={58} color={INK}/>
    <Panel>
      <Sequence from={0} durationInFrames={pf}><Screen src={p.dir + p.process.screen} zooms={p.process.zooms}/></Sequence>
      {r && <Sequence from={rs} durationInFrames={rf}><Screen src={p.dir + r.screen} zooms={r.zooms} from={r.start}/></Sequence>}
    </Panel>
    {t < rs && <Blurs list={p.process.blurs} zooms={p.process.zooms}/>}
    {inResult && <Blurs list={r?.blurs} zooms={r?.zooms}/>}
    {p.steps.map(s => <Sequence key={s.n} from={sec(s.spot[0])} durationInFrames={sec(s.spot[1] - s.spot[0])}><Spotlight step={s} zooms={p.process.zooms}/></Sequence>)}
    {p.sketches.map(s => <Sequence key={s.art} from={sec(s.start)} durationInFrames={sec(s.end - s.start)}><PanelSketch s={s} sheet={sheets[s.art]} dir={p.dir}/></Sequence>)}
    {(p.callouts || []).map((c, i) => <Sequence key={`co-${i}`} from={sec(c.start)} durationInFrames={Math.max(1, sec(c.end - c.start))}><CalloutView c={c}/></Sequence>)}
    {r && <Sequence from={rs} durationInFrames={rf}><ResultStamp text={r.stamp} inTitle={r.stampInTitle}/></Sequence>}
    {p.process.face && <Sequence from={0} durationInFrames={pf}><Face src={p.dir + p.process.face} cuts={p.cuts}/></Sequence>}
    {r?.face && <Sequence from={rs} durationInFrames={rf}><Face src={p.dir + r.face} cuts={p.cuts} from={r.start}/></Sequence>}
    {beforeCta && <FaceTag list={p.process.faceLabels} t={t}/>}
    <Captions list={list} t={t}/>
    {inResult
      ? <div style={{position: 'absolute', left: TRACKER.x, top: TRACKER.y, width: TRACKER.w, height: TRACKER.h, borderRadius: TRACKER.h / 2, background: INK,
          color: PAPER, fontFamily: 'Heading', fontSize: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 14}}>
          <span style={{color: CORAL}}>✓</span>{p.doneText ?? `Все ${p.steps.length} шага готовы`}</div>
      : <Tracker steps={p.steps} t={t}/>}
    <Sequence from={0} durationInFrames={sec(p.hook.end)}><Hook p={p} sheet={sheets[p.hook.art]}/></Sequence>
    {/* above the hook: the story's clickable area is one rect for the whole video, so the button never disappears */}
    {beforeCta && <Button text={p.button}/>}
    {beforeCta && <div style={{position: 'absolute', left: 96, width: 888, top: 1694, display: 'flex', gap: 14, alignItems: 'center', justifyContent: 'center',
      fontSize: 34, color: MUTED}}><TgIcon size={40}/>Бесплатный Telegram-бот <span style={{fontFamily: 'Heading', color: INK}}>{p.cta.bot}</span></div>}
    <Sequence from={cs} durationInFrames={p.frames - cs}>
      <Audio src={staticFile('common/music.mp3')} volume={(x: number) => .22 * Math.min(1, x / 20, (p.frames - cs - x) / 30)}/>
      <Cta p={p} sheet={sheets.bot}/>
    </Sequence>
  </AbsoluteFill>;
}

export const unusedMutedDark = MUTED_DARK;
