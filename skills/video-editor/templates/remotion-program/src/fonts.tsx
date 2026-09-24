import {useEffect, useState} from 'react';
import {continueRender, delayRender, staticFile} from 'remotion';

const FACES: Array<[string, string, string]> = [
  ['Manrope', 'fonts/Manrope-var.ttf', '200 800'],
  ['Caveat', 'fonts/Caveat-var.ttf', '400 700'], // full OFL Caveat (Latin+Cyrillic+digits); the old Caveat-Regular.ttf was a 109-glyph subset
  ['JetBrains Mono', 'fonts/JetBrainsMono-Medium.ttf', '500'],
  ['JetBrains Mono', 'fonts/JetBrainsMono-Bold.ttf', '700'],
];

let loaded: Promise<void> | null = null;

const loadAll = () => {
  if (!loaded) {
    loaded = Promise.all(
      FACES.map(async ([family, file, weight]) => {
        const face = new FontFace(family, `url(${staticFile(file)})`, {weight});
        await face.load();
        (document.fonts as any).add(face);
      }),
    ).then(() => undefined);
  }
  return loaded;
};

// Holds the frame until every brand font is really loaded (no fallback-font frames).
export const useFonts = () => {
  const [handle] = useState(() => delayRender('fonts'));
  useEffect(() => {
    loadAll().then(() => continueRender(handle));
  }, [handle]);
};

export const UI = 'Manrope, sans-serif';
export const HAND = 'Caveat, cursive';
export const MONO = '"JetBrains Mono", monospace';
