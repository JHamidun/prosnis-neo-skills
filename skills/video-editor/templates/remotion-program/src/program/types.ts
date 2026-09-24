// EDL contract of the full-frame "Program" composition (architecture E).
// All times are integer frames of the OUTPUT clock (25 fps), [from, to) half-open.
// Coordinates: "stage" = 1920x1080 output canvas; "content" = pixel space of a feed
// (slide / sketch = 1920x1080, zoom clip = its own width x height, e.g. 2560x1440).
import {Rect} from '../tokens';
import {LayoutKey} from '../components/Layout';
import {ChatItem} from '../components/Chat';

export type Move = {frame: number; rect: Rect; dur?: number}; // focus rect in content px, eased from the previous key

export type Mark = {
  // INSIDE the slide: drawn in content space, follows punch-ins and morphs
  type: 'circle' | 'underline' | 'check' | 'arrow' | 'box' | 'pulse' | 'spotlight' | 'strike';
  rect: Rect; // content px (the thing being marked)
  from: number; // draw starts
  dur?: number; // draw frames (default by type)
  to?: number; // disappears (fade 8 f); default: feed end
  color?: string; // default coral
  seed?: string;
  from_side?: 'left' | 'right' | 'top' | 'bottom'; // arrow origin
  width?: number;
};

export type SketchSpec = {
  data: string; // public path of sketch JSON (style/showcase/sketch_prep.py)
  beats: Record<string, number>; // element id -> start frame (output clock)
  durs?: Record<string, number>; // element id -> draw frames (default by kind/ink amount)
  pen?: string[]; // element ids drawn with the visible marker (max 1-2 per slide)
  settle?: number; // frame of the crossfade to the clean slide image (default: last element end + 6)
};

export type Feed = {
  id: string;
  from: number;
  to: number;
  kind: 'zoom' | 'slide' | 'sketch' | 'video' | 'still';
  src: string; // public path: clip / slide png / deck video
  cw: number; // content width
  ch: number; // content height
  srcStart?: number; // zoom/video: frame inside the source to start at
  crop?: Rect; // content px visible when not punched (default full)
  moves?: Move[]; // punch-in / pan keyframes
  drift?: number; // subtle Ken-Burns scale gain per 10 s on static content (0.015-0.03), sign = direction
  xfade?: number; // crossfade-in frames from the previous feed (default 0 = hard cut of the source)
  sketch?: SketchSpec;
  slideImg?: string; // for kind sketch: the clean slide shown after the settle
  videoRect?: Rect; // kind video: where the clean deck video sits on the slide (content px) — slideImg behind it
  marks?: Mark[];
  blur?: {rect: Rect; from?: number; to?: number}[]; // privacy blur in content px
  tilePatch?: Rect; // P1 zoom feeds: burned camera tile (content px) — dimmed+blurred while punched in
  pulse?: {rect: Rect; from: number; dur?: number}[]; // element pulse (scale 1->1.06->1) in content px
};

export type CapWord = {w: string; s: number; e: number; key?: boolean};
export type CapCue = {start: number; end: number; lines: number[][]}; // indices into words
export type Hero = {from: number; to: number; text: string; em?: string; kicker?: string}; // key-phrase callout in the caption band

export type Poll = {
  id: string;
  from: number;
  to: number;
  title: string;
  kicker?: string;
  options: {key: string; label: string}[];
  votes: {frame: number; key: string}[];
  reveal?: {frame: number; key: string}; // correct answer tick
};

export type Reaction = {frame: number; kind: string; msgId?: number; origin?: 'chat' | 'cam' | 'main' | [number, number]};

export type Doodle = {
  // AROUND the slide: stage px (to_content = target point inside the slide, mapped through the window)
  type: 'arrow' | 'label' | 'stat' | 'stars' | 'bracket' | 'circle_stage';
  from: number;
  to?: number;
  dur?: number;
  at: [number, number]; // stage px start / anchor
  to_content?: [number, number]; // arrow tip in content px of the active feed
  tip?: [number, number]; // arrow tip in stage px (if no to_content)
  text?: string;
  size?: number;
  color?: string;
  value?: number; // stat count-up target
  prefix?: string;
  suffix?: string;
  bend?: number;
  rotate?: number;
  align?: 'left' | 'center' | 'right';
  seed?: string;
};

export type ChapterSpec = {from: number; n: number; time: string; lines: string[]; note?: string; theme?: 'paper' | 'dark'; fromLayout: string; toLayout: string};
export type LowerThirdSpec = {person: string; from: number; to: number};
export type WinnerSpec = {from: number; to: number; kicker: string; name: string; prize: string};
export type ConfettiSpec = {frame: number; origin: [number, number]; count?: number; spread?: number; seed?: string};
export type ChipSpec = {from: number; to: number; text: string};
export type ToastSpec = {from: number; to: number; name: string; text: string; label?: string};
export type TagSpec = {from: number; to: number; text: string};

export type EDL = {
  id: string;
  durationInFrames: number;
  layouts: LayoutKey[];
  feeds: Feed[];
  cam?: {src: string; srcStart?: number; from?: number; to?: number; cw?: number; ch?: number};
  cams?: {src: string; srcStart: number; from: number; to: number}[]; // camera track split at cuts / inserted cards
  words?: CapWord[];
  cues?: CapCue[];
  heroes?: Hero[];
  chat?: ChatItem[];
  polls?: Poll[];
  reactions?: Reaction[];
  lowerThirds?: LowerThirdSpec[];
  doodles?: Doodle[];
  chapters?: ChapterSpec[];
  winners?: WinnerSpec[];
  confetti?: ConfettiSpec[];
  chips?: ChipSpec[];
  toasts?: ToastSpec[];
  tags?: TagSpec[];
  intro?: {titleFrom: number; titleTo: number}; // sting + title card of the intro (Intro.tsx) over the hidden window
  outro?: {from: number};
  fadeOut?: number; // frames of fade to black at the end
};
