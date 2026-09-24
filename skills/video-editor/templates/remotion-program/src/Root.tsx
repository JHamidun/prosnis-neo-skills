import React from 'react';
import {AbsoluteFill, Composition, Still} from 'remotion';
import {ChapterCard} from './components/ChapterCard';
import {Intro} from './components/Intro';
import {LowerThird} from './components/LowerThird';
import {Outro} from './components/Outro';
import {Stage} from './components/Stage';
import {useFonts} from './fonts';
import {C, T} from './tokens';
import {Program} from './program/Program';

const W = T.canvas.width;
const H = T.canvas.height;
const FPS = T.canvas.fps;

// Base plate for the ffmpeg-compose fallback (architecture D): stage + soft shadows under the feed
// windows of one layout. The main path (architecture E) renders everything in "Program".
const Plate: React.FC<{layout: string}> = ({layout}) => {
  const L = T.layout[layout];
  return (
    <AbsoluteFill>
      <Stage />
      {['main'].map((k) =>
        L[k] ? (
          <div key={k} style={{position: 'absolute', left: L[k][0], top: L[k][1], width: L[k][2], height: L[k][3], borderRadius: T.radius.frame, background: '#000', boxShadow: C.frame_shadow}} />
        ) : null,
      )}
    </AbsoluteFill>
  );
};

const Fonts: React.FC<{children: React.ReactNode}> = ({children}) => {
  useFonts();
  return <>{children}</>;
};

const EMPTY_EDL = {id: 'empty', durationInFrames: 50, layouts: [{frame: 0, layout: 'studio'}], feeds: []};

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="Program"
      component={Program as any}
      durationInFrames={50}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={{edl: EMPTY_EDL} as any}
      calculateMetadata={({props}: any) => ({durationInFrames: props.edl.durationInFrames})}
    />
    <Still id="StageStill" component={Stage} width={W} height={H} />
    <Still id="PlateStudio" component={() => <Plate layout="studio" />} width={W} height={H} />
    <Still id="PlateFull" component={() => <Plate layout="full" />} width={W} height={H} />
    <Composition
      id="ChapterCardDemo"
      component={(p: any) => (
        <Fonts>
          <AbsoluteFill style={{background: C.stage_bottom}}>
            <Stage />
            <div style={{position: 'absolute', left: 40, top: 40, width: 1440, height: 810, borderRadius: 22, background: '#111'}} />
            <ChapterCard {...p} />
          </AbsoluteFill>
        </Fonts>
      )}
      durationInFrames={T.chapter_card.duration_frames}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={{n: 3, time: '24:15', lines: ['Агенты, которые', 'работают за вас'], note: 'три живых примера', theme: 'dark'}}
    />
    <Composition
      id="ChapterCardPaper"
      component={(p: any) => (
        <Fonts>
          <AbsoluteFill style={{background: C.stage_bottom}}>
            <Stage />
            <ChapterCard {...p} />
          </AbsoluteFill>
        </Fonts>
      )}
      durationInFrames={T.chapter_card.duration_frames}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={{n: 4, time: '41:30', lines: ['Конференция', 'под ключ за неделю'], note: 'пример из эфира', theme: 'paper', fromRect: T.layout.full.main, toRect: T.layout.studio.main}}
    />
    <Composition
      id="LowerThirdDemo"
      component={() => (
        <Fonts>
          <AbsoluteFill style={{background: C.stage_bottom}}>
            <Stage />
            <div style={{position: 'absolute', left: 40, top: 40, width: 1440, height: 810, borderRadius: 22, background: '#1b1b1b'}} />
            <LowerThird person={T.lower_third.people[0]?.id} from={0} to={124} anchor={T.layout.studio.lower_third_anchor} />
          </AbsoluteFill>
        </Fonts>
      )}
      durationInFrames={125}
      fps={FPS}
      width={W}
      height={H}
    />
    <Composition id="Outro" component={() => <Fonts><Outro /></Fonts>} durationInFrames={T.outro.duration_s * FPS} fps={FPS} width={W} height={H} />
    <Composition
      id="Intro"
      component={(p: any) => (
        <Fonts>
          <Intro {...p} />
        </Fonts>
      )}
      durationInFrames={T.intro.duration_s * FPS}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={{teaser: [{src: 'demo/teaser.mp4', startFrom: 0, frames: 170}, {src: 'demo/teaser.mp4', startFrom: 330, frames: 168}]}}
    />
  </>
);
