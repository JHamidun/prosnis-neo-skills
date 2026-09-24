import React from 'react';
import {spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {MONO, UI} from '../fonts';
import {C, Rect, T} from '../tokens';
import {EMOJI_TO_ICON, SketchIcon} from '../program/icons';

export type ChatItem = {
  id: number;
  frame: number; // frame the message lands on screen
  name: string; // already privacy-filtered first name or «Участник»
  text: string;
  team: boolean;
  h: number; // bubble height measured offline with the same font metrics
  hl: boolean; // highlighted question / key reaction
  reply?: string | null;
  color: string;
  aggregate?: {frame: number; count: number}[];
  vote?: string; // compact poll-answer bubble (name + big answer chip)
  reacts?: {frame: number; emoji: string}[]; // Zoom reactions on this message -> counter badge
};

const ch = T.chat;
const HEADER = ch.header.height;

const Bubble: React.FC<{it: ChatItem; f: number; fps: number}> = ({it, f, fps}) => {
  const tpx = it.hl ? ch.highlight.text_px : ch.text_px;
  if (it.aggregate) {
    // «+ ×N» chip: one bubble instead of a flood of identical one-char messages.
    let count = 0;
    let at = it.frame;
    for (const s of it.aggregate) if (s.frame <= f) {
      count = s.count;
      at = s.frame;
    }
    const bump = spring({frame: f - at, fps, config: T.motion.spring_pop});
    const sc = 1 + 0.18 * (1 - bump);
    return (
      <div
        style={{
          height: it.h,
          boxSizing: 'border-box',
          borderRadius: T.radius.bubble,
          background: C.bubble_bg,
          outline: `1px solid ${C.bubble_edge}`,
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: `0 ${ch.bubble_pad[1]}px`,
          fontFamily: UI,
        }}
      >
        <div style={{width: 38, height: 38, borderRadius: 19, background: C.coral_soft, color: C.coral, fontWeight: 800, fontSize: 30, lineHeight: '38px', textAlign: 'center'}}>+</div>
        <div style={{color: C.bubble_text, fontSize: 20, fontWeight: 600}}>реакции в чате</div>
        <div style={{marginLeft: 'auto', color: C.coral, fontWeight: 800, fontSize: 28, transform: `scale(${sc})`, transformOrigin: 'right center', fontVariantNumeric: 'tabular-nums'}}>×{count}</div>
      </div>
    );
  }
  if (it.vote) {
    return (
      <div
        style={{
          height: it.h,
          boxSizing: 'border-box',
          borderRadius: 14,
          background: C.bubble_bg,
          outline: `1px solid ${C.bubble_edge}`,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '0 8px 0 14px',
          fontFamily: UI,
        }}
      >
        <span style={{color: it.color, fontWeight: 700, fontSize: ch.name_px}}>{it.name}</span>
        <span style={{color: C.muted, fontSize: 15, fontWeight: 500}}>ответ</span>
        <span style={{marginLeft: 'auto', minWidth: 34, height: 30, borderRadius: 10, background: C.coral_soft, color: C.coral, fontWeight: 800, fontSize: 20, lineHeight: '30px', textAlign: 'center', padding: '0 8px'}}>{it.vote}</span>
      </div>
    );
  }
  const badge = (it.reacts ?? []).filter((r) => r.frame <= f);
  const byEmoji: Record<string, {n: number; at: number}> = {};
  for (const r of badge) byEmoji[r.emoji] = {n: (byEmoji[r.emoji]?.n ?? 0) + 1, at: r.frame};
  return (
    <div style={{position: 'relative'}}>
    {Object.keys(byEmoji).length ? (
      <div style={{position: 'absolute', right: 10, top: 8, zIndex: 2, display: 'flex', gap: 6}}>
        {Object.entries(byEmoji).map(([e, v]) => {
          const b = spring({frame: f - v.at, fps, config: {damping: 9, stiffness: 200, mass: 0.5}});
          return (
            <div key={e} style={{display: 'flex', alignItems: 'center', gap: 4, height: 28, padding: '0 9px 0 5px', borderRadius: 14, background: '#262A52', outline: `1px solid ${C.coral_line}`, transform: `scale(${0.6 + 0.4 * b + 0.15 * Math.sin(Math.min(1, b) * Math.PI)})`, transformOrigin: 'right center'}}>
              <SketchIcon kind={EMOJI_TO_ICON[e] ?? 'star'} size={22} p={1} q={1} seed={'b' + it.id + e} />
              <span style={{fontFamily: UI, fontWeight: 800, fontSize: 15, color: C.ink_on_dark}}>{v.n}</span>
            </div>
          );
        })}
      </div>
    ) : null}
    <div
      style={{
        height: it.h,
        boxSizing: 'border-box',
        borderRadius: T.radius.bubble,
        padding: `${ch.bubble_pad[0]}px ${ch.bubble_pad[1]}px`,
        background: it.team ? C.bubble_team_bg : C.bubble_bg,
        outline: it.hl ? ch.highlight.border : `1px solid ${it.team ? C.bubble_team_edge : C.bubble_edge}`,
        boxShadow: it.hl ? ch.highlight.glow : undefined,
        overflow: 'hidden',
        fontFamily: UI,
      }}
    >
      <div style={{display: 'flex', alignItems: 'center', gap: 8, height: Math.round(ch.name_px * 1.3), marginBottom: 4}}>
        <span style={{color: it.team ? C.coral : it.color, fontWeight: 700, fontSize: ch.name_px}}>{it.name}</span>
        {it.team ? (
          <span style={{fontFamily: MONO, fontSize: 12, letterSpacing: '0.1em', color: C.coral, border: `1px solid ${C.coral_line}`, borderRadius: 6, padding: '1px 6px'}}>КОМАНДА</span>
        ) : null}
      </div>
      {it.hl && it.text.includes('?') ? (
        <div style={{fontFamily: MONO, fontSize: 13, letterSpacing: '0.14em', color: C.coral, height: 26, lineHeight: '22px'}}>ВОПРОС ИЗ ЧАТА</div>
      ) : null}
      {it.reply ? (
        <div
          style={{
            borderLeft: `3px solid ${C.coral}`,
            paddingLeft: 8,
            color: C.muted,
            fontSize: 16,
            height: 22,
            lineHeight: '22px',
            marginBottom: 8,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {it.reply}
        </div>
      ) : null}
      <div style={{color: C.bubble_text, fontSize: tpx, lineHeight: ch.text_line_height, fontWeight: it.hl ? 600 : 500}}>{it.text}</div>
    </div>
    </div>
  );
};

// Chat column: newest message at the bottom, older ones pushed up by a critically damped
// spring (no jitter), new bubble pops in with a light spring, top edge fades out.
export const Chat: React.FC<{items: ChatItem[]; rect: Rect; opacity?: number; dx?: number; pin?: number}> = ({items, rect, opacity = 1, dx = 0, pin = 0}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (opacity <= 0.001) return null;
  const [x, y, w, h] = rect;
  const vis = items.filter((it) => it.frame <= f);
  const tail = vis.slice(-(ch.max_visible + 3));
  const listTop = HEADER + 10 + pin;
  const listH = h - listTop;
  // push-up offsets: each later bubble contributes its height * its own reflow spring
  const reflow = tail.map((it) => spring({frame: f - it.frame, fps, config: T.motion.spring_reflow}));
  const offs = tail.map((_, i) => {
    let o = 0;
    for (let j = i + 1; j < tail.length; j++) o += (tail[j].h + ch.gap) * reflow[j];
    return o;
  });
  const live = Math.floor(f / (fps * 0.8)) % 2 === 0;
  return (
    <div style={{position: 'absolute', left: x, top: y, width: w, height: h, opacity, transform: `translateX(${dx}px)`}}>
      <div style={{height: HEADER, display: 'flex', alignItems: 'center', gap: 10, fontFamily: MONO, fontSize: ch.header.font_px, letterSpacing: ch.header.tracking, color: C.lavender}}>
        <span style={{width: 9, height: 9, borderRadius: 5, background: C.coral, opacity: live ? 1 : 0.35}} />
        {ch.header.text}
        <span style={{flex: 1, height: 1, background: 'rgba(201,203,224,0.14)', marginLeft: 6}} />
      </div>
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: listTop,
          width: w,
          height: listH,
          overflow: 'hidden',
          WebkitMaskImage: `linear-gradient(180deg, transparent 0px, black ${ch.fade_top_px}px)`,
          maskImage: `linear-gradient(180deg, transparent 0px, black ${ch.fade_top_px}px)`,
        }}
      >
        {tail.map((it, i) => {
          const bottom = offs[i];
          if (bottom > listH + 20) return null;
          // the new bubble pops only after the column has started to make room (no overlap)
          const s = spring({frame: f - it.frame - 4, fps, config: T.motion.spring_pop});
          return (
            <div
              key={it.id}
              style={{
                position: 'absolute',
                left: 0,
                width: w,
                bottom,
                opacity: Math.min(1, s * 1.6),
                transform: `translateY(${(1 - s) * 14}px) scale(${0.92 + 0.08 * s})`,
                transformOrigin: 'left bottom',
              }}
            >
              <Bubble it={it} f={f} fps={fps} />
            </div>
          );
        })}
      </div>
    </div>
  );
};
