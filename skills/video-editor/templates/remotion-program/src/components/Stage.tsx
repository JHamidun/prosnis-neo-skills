import React from 'react';
import {AbsoluteFill} from 'remotion';
import {C} from '../tokens';

// Static branded stage: deep navy gradient + two soft glows + faint dot grid.
// In the ffmpeg path this is rendered ONCE to bg.png (composition "StageStill").
export const Stage: React.FC = () => (
  <AbsoluteFill
    style={{
      background: `radial-gradient(1100px 700px at 22% 30%, ${C.stage_glow_2}, transparent 70%),
        radial-gradient(900px 620px at 88% 92%, ${C.stage_glow}, transparent 70%),
        linear-gradient(180deg, ${C.stage_top} 0%, ${C.stage_bottom} 100%)`,
    }}
  >
    <AbsoluteFill
      style={{
        backgroundImage: 'radial-gradient(rgba(201,203,224,0.07) 1.2px, transparent 1.3px)',
        backgroundSize: '28px 28px',
        maskImage: 'radial-gradient(1200px 800px at 50% 45%, black 20%, transparent 85%)',
        WebkitMaskImage: 'radial-gradient(1200px 800px at 50% 45%, black 20%, transparent 85%)',
      }}
    />
  </AbsoluteFill>
);
