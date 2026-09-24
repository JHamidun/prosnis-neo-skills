// Video layer for the Program. Clips we ingested ourselves (NVENC, GOP 25, no B-frames: zoom feeds
// full/clips/*, camera tiles) go through @remotion/media <Video> (Mediabunny + WebCodecs decode in
// the renderer): 2x faster than <OffthreadVideo> on the loaded machine, where OffthreadVideo's
// per-frame BMP over HTTP stalled at ~1 fps and timed out on p2_main. Deck videos (third-party
// encodes; one hung WebCodecs in the bench) stay on <OffthreadVideo>.
import React from 'react';
import {OffthreadVideo} from 'remotion';
import {Video} from '@remotion/media';

export const Vid: React.FC<{src: string; startFrom?: number; style?: React.CSSProperties}> = ({src, startFrom, style}) => {
  if (!src.includes('/full/clips/')) {
    return <OffthreadVideo src={src} startFrom={startFrom ?? 0} muted style={style} />;
  }
  const {objectFit, ...rest} = style ?? {};
  return <Video src={src} trimBefore={startFrom ? startFrom : undefined} muted objectFit={(objectFit as any) ?? 'fill'} style={rest} />;
};
