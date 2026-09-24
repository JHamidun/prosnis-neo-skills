import {Composition, staticFile} from 'remotion';
import {StoryV3, StoryProps} from './StoryV3';

// Props come from public/clips/<id>/story.json via --props; calculateMetadata sets the length.
export const Root = () => <Composition
  id="StoryV3"
  component={StoryV3 as unknown as React.FC<Record<string, unknown>>}
  width={1080}
  height={1920}
  fps={30}
  durationInFrames={300}
  defaultProps={{clip: 'b5_01'} as Record<string, unknown>}
  calculateMetadata={async ({props}) => {
    const clip = (props as {clip?: string}).clip ?? 'b5_01';
    const story = await fetch(staticFile(`clips/${clip}/story.json`)).then(r => r.json()) as StoryProps;
    return {durationInFrames: story.frames, props: story as unknown as Record<string, unknown>};
  }}
/>;
