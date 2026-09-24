import React from 'react';
import {Vid} from '../program/Vid';
import {AbsoluteFill, Img, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {MONO, UI} from '../fonts';
import {BRAND, C, Rect, T} from '../tokens';
import {easeEnter, easeExit, easeMorph, lerpRect} from './Layout';
import {Draw, markerUnderline, rays} from './Sketch';
import {Stage} from './Stage';
import {SketchArt} from '../program/SketchReveal';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const B = T.intro.beats_s;

// Brand mark for the sting (tokens.brand.mark: {path, bracket_left?, bracket_right?, w, h} in SVG units)
// - drawn as a stroke, then filled. Texts of the title card come from tokens.intro.
const I = T.intro;
const MARK = BRAND.mark ?? null;
const MW: number = MARK?.w ?? 31;
const MH: number = MARK?.h ?? 29;

export type TeaserClip = {src: string; startFrom: number; frames: number; quote?: string};

// 24 s: sting (mark draws itself) -> title card -> teaser (3-4 strongest moments in the SAME
// window the webinar will use) -> handoff (window already sits at the studio main rect, so the
// first real frame continues without a jump).
export type IntroArt = {data: string; parts: {ids: string[]; box: [number, number, number, number]; start: number; speed?: number}[]};

export const Intro: React.FC<{teaser: TeaserClip[]; bare?: boolean; art?: IntroArt}> = ({teaser, bare = false, art}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = (sec: number) => Math.round(sec * fps);

  // --- sting
  const stroke = interpolate(f, [4, 26], [0, 1], {...clamp, easing: easeMorph});
  const fill = interpolate(f, [20, 32], [0, 1], clamp);
  const br = interpolate(f, [26, 40], [0, 1], {...clamp, easing: easeMorph});
  const markMove = interpolate(f, [s(B.sting[1]) - 14, s(B.sting[1]) + 4], [0, 1], {...clamp, easing: easeMorph});
  const markScale = 9 - 7.2 * markMove; // 31 units * 9 = 279 px wide -> 56 px next to the label
  const markX = (960 - (MW / 2) * 9) * (1 - markMove) + 150 * markMove;
  const markY = (540 - (MH / 2) * 9) * (1 - markMove) + 148 * markMove;

  // --- title card
  const t0 = s(B.title[0]);
  const lab = spring({frame: f - t0, fps, config: T.motion.spring_plate});
  const l1 = interpolate(f, [t0 + 4, t0 + 22], [0, 1], {...clamp, easing: easeEnter});
  const l2 = interpolate(f, [t0 + 10, t0 + 30], [0, 1], {...clamp, easing: easeEnter});
  const ul = interpolate(f, [t0 + 26, t0 + 46], [0, 1], {...clamp, easing: easeMorph});
  const who = spring({frame: f - t0 - 30, fps, config: T.motion.spring_plate});
  const titleOut = interpolate(f, [s(B.teaser[0]) - 8, s(B.teaser[0]) + 4], [1, 0], {...clamp, easing: easeExit});

  // --- teaser window grows from a small card to the studio main rect
  const tz = s(B.teaser[0]);
  const win = interpolate(f, [tz - 6, tz + 12], [0, 1], {...clamp, easing: easeMorph});
  const main: Rect = T.layout.studio.main;
  const small: Rect = [main[0] + main[2] * 0.25, main[1] + main[3] * 0.25, main[2] * 0.5, main[3] * 0.5];
  const wr = lerpRect(small, main, win);
  const tag = interpolate(f, [tz + 10, tz + 22, s(B.handoff[0]), s(B.handoff[0]) + 10], [0, 1, 1, 0], clamp);
  let acc = tz;
  const seqs = teaser.map((c) => {
    const from = acc;
    acc += c.frames;
    return {c, from};
  });

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{opacity: bare ? titleOut : 1}}>
        <Stage />
      </AbsoluteFill>
      {/* mark */}
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0, opacity: titleOut}}>
        {MARK ? (
          <g transform={`translate(${markX} ${markY}) scale(${markScale})`}>
            <path d={MARK.path} fill={C.coral} opacity={fill} />
            <Draw d={MARK.path} p={stroke} stroke={C.coral} width={0.5} opacity={1 - fill} />
            {MARK.bracket_left ? <Draw d={MARK.bracket_left} p={br} stroke={C.coral} width={1.8} opacity={0.62} /> : null}
            {MARK.bracket_right ? <Draw d={MARK.bracket_right} p={br} stroke={C.coral} width={1.8} opacity={0.62} /> : null}
          </g>
        ) : null}
      </svg>
      {/* title card */}
      {f >= t0 - 2 && f < tz + 6 ? (
        <div style={{position: 'absolute', inset: 0, opacity: titleOut}}>
          <div style={{position: 'absolute', left: 230, top: 160, fontFamily: MONO, fontWeight: 700, fontSize: 24, letterSpacing: '0.16em', color: C.coral, opacity: lab, transform: `translateY(${(1 - lab) * 10}px)`}}>
            {I.kicker}
          </div>
          <div style={{position: 'absolute', left: 150, top: 330, fontFamily: UI, fontWeight: 800, fontSize: 132, letterSpacing: '-0.03em', color: C.ink_on_dark, lineHeight: 1, clipPath: `inset(-30px ${(1 - l1) * 100}% -30px 0)`}}>
            {I.title?.[0]}
            <span style={{color: C.coral}}>{I.title?.[1]}</span>
          </div>
          <div style={{position: 'absolute', left: 150, top: 480, fontFamily: UI, fontWeight: 700, fontSize: 72, letterSpacing: '-0.02em', color: C.lavender, lineHeight: 1.1, clipPath: `inset(-30px ${(1 - l2) * 100}% -30px 0)`}}>
            {I.subtitle}
          </div>
          <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
            <Draw d={markerUnderline(146, I.underline_x1 ?? 1180, 580, 'iu')} p={ul} stroke={C.coral} width={8} />
            {rays(I.rays_at?.[0] ?? 1250, I.rays_at?.[1] ?? 400, 1, 'ir', 34).map((d, i) => (
              <Draw key={i} d={d} p={interpolate(f, [t0 + 20 + i * 3, t0 + 34 + i * 3], [0, 1], clamp)} stroke={C.coral} width={5} />
            ))}
          </svg>
          <div style={{position: 'absolute', left: 150, top: 700, display: 'flex', alignItems: 'center', gap: 22, opacity: who, transform: `translateY(${(1 - who) * 14}px)`}}>
            <div style={{width: 6, height: 74, borderRadius: 3, background: C.coral}} />
            <div>
              <div style={{fontFamily: UI, fontWeight: 800, fontSize: 38, color: C.ink_on_dark}}>{I.host?.name}</div>
              <div style={{fontFamily: UI, fontWeight: 500, fontSize: 24, color: C.lavender, marginTop: 4}}>{I.host?.role}</div>
            </div>
          </div>
          {BRAND.logo ? <Img src={staticFile(BRAND.logo)} style={{position: 'absolute', right: 150, bottom: 110, height: 64, opacity: who * 0.9}} /> : null}
          {/* live sketch of the deck's own art (EDL intro.art: element ids of a traced slide) draws itself next to the title */}
          {art
            ? art.parts.map((pt, i) => (
                <SketchArt key={i} data={art.data} ids={pt.ids} start={pt.start} box={pt.box} uid={`intro${i}`} blend="lighten" speed={pt.speed ?? 1} />
              ))
            : null}
        </div>
      ) : null}
      {/* teaser */}
      {!bare && f >= tz - 6 ? (
        <>
          <div
            style={{
              position: 'absolute',
              left: wr[0],
              top: wr[1],
              width: wr[2],
              height: wr[3],
              borderRadius: T.radius.frame,
              overflow: 'hidden',
              background: '#000',
              boxShadow: C.frame_shadow,
              opacity: Math.min(1, win * 2),
            }}
          >
            {seqs.map(({c, from}, i) => (
              <Sequence key={i} from={from} durationInFrames={c.frames} layout="none">
                <Vid src={staticFile(c.src)} startFrom={c.startFrom} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
              </Sequence>
            ))}
          </div>
          <div
            style={{
              position: 'absolute',
              left: main[0] + 24,
              top: main[1] + 22,
              padding: '8px 14px',
              borderRadius: 10,
              background: 'rgba(1,3,52,0.86)',
              fontFamily: MONO,
              fontWeight: 700,
              fontSize: 18,
              letterSpacing: '0.14em',
              color: C.coral,
              opacity: tag,
            }}
          >
            {I.teaser_tag ?? 'ЛУЧШЕЕ ИЗ ЭФИРА'}
          </div>
        </>
      ) : null}
    </AbsoluteFill>
  );
};
