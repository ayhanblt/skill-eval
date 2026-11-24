import React from "react";
import { Audio } from "@remotion/media";
import { interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

export const NarrationAudio: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const fadeFrames = Math.max(1, Math.round(0.6 * fps));
  const fadeOutStart = Math.max(fadeFrames + 1, durationInFrames - fadeFrames);

  const volume = interpolate(
    frame,
    [0, fadeFrames, fadeOutStart, durationInFrames],
    [0, 1, 1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    },
  );

  return <Audio src={staticFile("narration.wav")} volume={volume} />;
};
