// Single source of truth lives in <job>/style/tokens.json (shared with the EDL builder and the
// ffmpeg scripts). The Remotion project sits in <job>/remotion, so the path is ../../style.
// Imported JSON is baked into the bundle: after editing tokens.json, re-bundle (gotcha G-R2).
import raw from '../../style/tokens.json';

export const T: any = raw;
export type Rect = [number, number, number, number];
export const C = T.color;
export const FPS: number = T.canvas.fps;
// Brand assets (public paths) and texts come from tokens.brand / tokens.intro / tokens.outro.
export const BRAND: any = T.brand ?? {};
