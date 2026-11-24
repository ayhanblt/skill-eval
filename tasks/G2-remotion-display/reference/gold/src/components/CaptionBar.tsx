import React from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { CaptionItem } from "../schema";

type Props = {
  captions: readonly CaptionItem[];
  accentColor: string;
};

export const CaptionBar: React.FC<Props> = ({ captions, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentMs = (frame / fps) * 1000;

  const active = captions.find(
    (c) => currentMs >= c.startMs && currentMs < c.endMs,
  );
  if (!active) {
    return null;
  }

  const localFrame = Math.max(0, ((currentMs - active.startMs) / 1000) * fps);
  const opacity = interpolate(localFrame, [0, Math.round(fps * 0.2)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  return (
    <div
      style={{
        position: "absolute",
        left: 120,
        right: 120,
        bottom: 36,
        display: "flex",
        justifyContent: "center",
        opacity,
      }}
    >
      <div
        style={{
          backgroundColor: "rgba(10, 15, 28, 0.86)",
          border: `2px solid ${accentColor}`,
          borderRadius: 12,
          padding: "14px 28px",
          color: "#F8FAFC",
          fontFamily: "Liberation Sans, DejaVu Sans, sans-serif",
          fontSize: 24,
          fontWeight: 600,
          textAlign: "center",
          lineHeight: 1.35,
          maxWidth: 980,
        }}
      >
        {active.text}
      </div>
    </div>
  );
};
