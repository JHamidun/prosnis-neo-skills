// Architecture E: ONE full-frame composition driven by an EDL (types.ts). Rendered in chunks by
// render_program.mjs (persistent node process, parallel chunks), ffmpeg only ingests sources,
// concatenates chunks and muxes the separately mixed audio.
import React from 'react';
import {AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {Vid} from './Vid';
import {ChapterCard} from '../components/ChapterCard';
import {Chat} from '../components/Chat';
import {Intro} from '../components/Intro';
import {bandAt, layoutAt, lerp, lerpRect, slotPresence, slotRect} from '../components/Layout';
import {LowerThird} from '../components/LowerThird';
import {Outro} from '../components/Outro';
import {Stage} from '../components/Stage';
import {useFonts} from '../fonts';
import {BRAND, C, Rect, T} from '../tokens';
import {Captions2} from './Captions2';
import {FeedView, contentToWindow, focusAt} from './FeedView';
import {Confetti, Doodles, HeroCallout, Pill, POLL_H, PollCard, Reactions, WinnerBanner, pollPresence} from './Overlays';
import {EDL} from './types';

const HEADER = T.chat.header.height;
const cl = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

export const Program: React.FC<{edl: EDL}> = ({edl}) => {
  useFonts();
  const f = useCurrentFrame();
  const st = layoutAt(edl.layouts, f);
  const main = slotRect(st, 'main') as Rect;
  const hidA = !!T.layout[st.from].hidden;
  const hidB = !!T.layout[st.to].hidden;
  const mainO = hidA && hidB ? 0 : hidA ? st.p : hidB ? 1 - st.p : 1;
  const camR = slotRect(st, 'cam');
  const camP = slotPresence(st, 'cam');
  const chatR = slotRect(st, 'chat');
  const chatP = slotPresence(st, 'chat');
  const logoR = slotRect(st, 'logo');
  const logoP = slotPresence(st, 'logo');
  const band = bandAt(st);
  const a0 = T.layout[st.from].lower_third_anchor;
  const a1 = T.layout[st.to].lower_third_anchor;
  const anchor = [lerp(a0[0], a1[0], st.p), lerp(a0[1], a1[1], st.p)];

  // tags/chips sit on the top-left corner of the BIG window (in face_xl that is the camera)
  const bigWin = (name: string): Rect => (name === 'face_xl' ? T.layout.face_xl.cam : T.layout[name].main);
  const tagWin = lerpRect(bigWin(st.from), bigWin(st.to), st.p);
  const active = edl.feeds.filter((fd) => f >= fd.from && f < fd.to).sort((a, b) => a.from - b.from);
  const top = active[active.length - 1];
  const mapContent = (pt: [number, number]): [number, number] => {
    if (!top) return pt;
    const {k, tx, ty} = contentToWindow(main, focusAt(top, f));
    return [main[0] + tx + pt[0] * k, main[1] + ty + pt[1] * k];
  };

  const {v: pollV, poll} = pollPresence(edl.polls ?? [], f);
  const pin = poll ? pollV * (POLL_H(poll) + 12) : 0;
  const heroOn = (edl.heroes ?? []).some((h) => f >= h.from && f < h.to) || (edl.winners ?? []).some((w) => f >= w.from && f < w.to);
  const reactOrigin: [number, number, number] =
    chatR && chatP.o > 0.5
      ? [chatR[0] + 60, chatR[0] + chatR[2] - 60, chatR[1] + chatR[3] - 50]
      : camR && camP.o > 0.5
        ? [camR[0] + 40, camR[0] + camR[2] - 40, camR[1] + camR[3] + 40]
        : [main[0] + main[2] - 90, main[0] + main[2] + 70, main[1] + main[3] - 10];
  // each reaction keeps the origin of the layout it was spawned in; icons born in the chat column
  // fade with the column when it leaves (they must not float over a full-screen demo)
  const reacts = (edl.reactions ?? []).map((r) => {
    if (r.origin || f < r.frame || f > r.frame + 72) return r;
    const st0 = layoutAt(edl.layouts, r.frame);
    const cr = slotRect(st0, 'chat');
    if (cr && slotPresence(st0, 'chat').o > 0.5) return {...r, origin: [cr[0] + 60 + ((r.frame * 37) % Math.max(1, cr[2] - 120)), cr[1] + cr[3] - 50] as [number, number], _fade: chatP.o};
    return r;
  });
  const fade = edl.fadeOut ? interpolate(f, [edl.durationInFrames - edl.fadeOut, edl.durationInFrames - 1], [0, 1], cl) : 0;
  const chapterOn = (edl.chapters ?? []).some((c) => f >= c.from + 14 && f < c.from + 78);
  // side UI (camera, chat, logo) hides under a chapter card and slides back in after it (no pop)
  let sideQ = 1;
  for (const c of edl.chapters ?? []) {
    if (f >= c.from + 12 && f < c.from + 96) sideQ = Math.min(sideQ, interpolate(f, [c.from + 12, c.from + 13, c.from + 80, c.from + 94], [1, 0, 0, 1], cl));
  }
  const cams = edl.cams ?? (edl.cam ? [{src: edl.cam.src, srcStart: edl.cam.srcStart ?? 0, from: edl.cam.from ?? 0, to: edl.cam.to ?? edl.durationInFrames}] : []);

  return (
    <AbsoluteFill style={{background: C.stage_bottom}}>
      <Stage />
      {/* main window */}
      <div
        style={{
          position: 'absolute',
          left: main[0],
          top: main[1],
          width: main[2],
          height: main[3],
          borderRadius: T.radius.frame,
          overflow: 'hidden',
          background: '#000',
          boxShadow: C.frame_shadow,
          opacity: mainO,
          outline: `1px solid ${C.frame_edge}`,
          outlineOffset: -1,
        }}
      >
        {chapterOn
          ? null
          : active.map((fd) => (
              <FeedView key={fd.id} feed={fd} f={f} win={main} uid={fd.id} opacity={fd.xfade ? interpolate(f, [fd.from, fd.from + fd.xfade], [0, 1], cl) : 1} />
            ))}
      </div>
      {/* camera */}
      {cams.some((c) => f >= c.from && f < c.to) && camR && camP.o > 0.001 && sideQ > 0.001 ? (
        <div
          style={{
            position: 'absolute',
            left: camR[0] + camP.dx + (1 - sideQ) * 40,
            top: camR[1],
            width: camR[2],
            height: camR[3],
            borderRadius: T.radius.pip,
            overflow: 'hidden',
            background: '#000',
            opacity: camP.o * mainO * sideQ,
            boxShadow: '0 12px 30px rgba(0,0,0,0.5)',
            outline: `1px solid ${C.frame_edge}`,
            outlineOffset: -1,
          }}
        >
          {cams.map((c, i) =>
            f >= c.from && f < c.to ? (
              <Sequence key={i} from={c.from} durationInFrames={c.to - c.from} layout="none">
                <Vid src={staticFile(c.src)} startFrom={c.srcStart} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
              </Sequence>
            ) : null,
          )}
        </div>
      ) : null}
      {/* chat column + pinned poll */}
      {chatR && chatP.o > 0.001 ? (
        <>
          <Chat items={edl.chat ?? []} rect={chatR} opacity={chatP.o * mainO * sideQ} dx={chatP.dx + (1 - sideQ) * 40} pin={pin} />
          {poll && pollV > 0.001 ? <PollCard poll={poll} f={f} v={pollV * chatP.o * sideQ} rect={[chatR[0] + chatP.dx + (1 - sideQ) * 40, chatR[1] + HEADER + 8, chatR[2], 0]} /> : null}
        </>
      ) : null}
      {logoR && logoP.o > 0.001 && BRAND.logo ? (
        <Img
          src={staticFile(BRAND.logo)}
          style={{position: 'absolute', left: logoR[0] + logoR[2] - 180, top: logoR[1] + 4, height: 38, opacity: 0.7 * logoP.o * mainO * sideQ, transform: `translateX(${logoP.dx}px)`}}
        />
      ) : null}
      {/* around the slide */}
      <Doodles items={edl.doodles ?? []} f={f} mapContent={mapContent} />
      {/* band: captions / hero / winner */}
      {edl.words && edl.cues ? <Captions2 words={edl.words} cues={edl.cues} band={band} hidden={heroOn || mainO < 0.5} /> : null}
      {(edl.heroes ?? []).map((h, i) => (
        <HeroCallout key={i} h={h} f={f} band={band} />
      ))}
      {(edl.winners ?? []).map((w, i) => (
        <WinnerBanner key={i} w={w} f={f} band={band} />
      ))}
      {(edl.lowerThirds ?? []).map((lt, i) => (
        <LowerThird key={i} person={lt.person} from={lt.from} to={lt.to} anchor={anchor} />
      ))}
      {(edl.chips ?? []).map((c, i) => (
        <Pill key={`c${i}`} text={c.text} f={f} from={c.from} to={c.to} at={[tagWin[0] + 24, tagWin[1] + 22]} coral />
      ))}
      {(edl.tags ?? []).map((c, i) => (
        <Pill key={`t${i}`} text={c.text} f={f} from={c.from} to={c.to} at={[tagWin[0] + 24, tagWin[1] + 22]} />
      ))}
      <Reactions items={reacts} f={f} origin={reactOrigin} />
      {(edl.confetti ?? []).map((c, i) => (
        <Confetti key={i} c={c} f={f} />
      ))}
      {(edl.chapters ?? []).map((c, i) => (
        <Sequence key={`ch${i}`} from={c.from} durationInFrames={T.chapter_card.duration_frames}>
          <ChapterCard
            n={c.n}
            time={c.time}
            lines={c.lines}
            note={c.note}
            theme={c.theme}
            fromRect={T.layout[c.fromLayout].main}
            toRect={T.layout[c.toLayout].main}
            art={(c as any).art}
          />
        </Sequence>
      ))}
      {edl.intro ? (
        <Sequence from={0} durationInFrames={edl.intro.titleTo}>
          <Intro teaser={[]} bare art={(edl.intro as any).art} />
        </Sequence>
      ) : null}
      {edl.outro ? (
        <Sequence from={edl.outro.from}>
          <Outro />
        </Sequence>
      ) : null}
      {fade > 0 ? <AbsoluteFill style={{background: '#000', opacity: fade}} /> : null}
    </AbsoluteFill>
  );
};
