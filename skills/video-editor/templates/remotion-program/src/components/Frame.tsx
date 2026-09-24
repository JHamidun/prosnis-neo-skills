import React from 'react';
import {C, Rect, T} from '../tokens';

// Rounded feed window: one faint edge + soft external shadow (reference: r~22, no double borders).
export const Frame: React.FC<{
  rect: Rect;
  radius?: number;
  opacity?: number;
  shadow?: boolean;
  children?: React.ReactNode;
  bg?: string;
}> = ({rect, radius = T.radius.frame, opacity = 1, shadow = true, children, bg = '#000'}) => {
  const [x, y, w, h] = rect;
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: w,
        height: h,
        borderRadius: radius,
        overflow: 'hidden',
        background: bg,
        opacity,
        boxShadow: shadow ? C.frame_shadow : undefined,
        outline: `1px solid ${C.frame_edge}`,
        outlineOffset: -1,
      }}
    >
      {children}
    </div>
  );
};
