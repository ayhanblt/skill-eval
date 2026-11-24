import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type Props = {
  title: string;
  subtitle: string;
  accentColor: string;
};

export const IntroScene: React.FC<Props> = ({ title, subtitle, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 120 },
  });
  const barWidth = interpolate(frame, [0, Math.round(1.1 * fps)], [0, 220], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const subtitleOpacity = interpolate(
    frame,
    [Math.round(0.35 * fps), Math.round(0.95 * fps)],
    [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.16, 1, 0.3, 1),
    },
  );

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        padding: "0 110px 70px 110px",
        fontFamily: "Liberation Sans, DejaVu Sans, sans-serif",
      }}
    >
      <div
        style={{
          width: barWidth,
          height: 6,
          backgroundColor: accentColor,
          borderRadius: 4,
          marginBottom: 28,
        }}
      />
      <h1
        style={{
          margin: 0,
          color: "#F8FAFC",
          fontSize: 64,
          fontWeight: 800,
          lineHeight: 1.12,
          letterSpacing: "-0.02em",
          opacity: progress,
          translate: `0px ${interpolate(progress, [0, 1], [36, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px`,
        }}
      >
        {title}
      </h1>
      <p
        style={{
          margin: "22px 0 0 0",
          color: "#CBD5E1",
          fontSize: 30,
          fontWeight: 500,
          lineHeight: 1.4,
          opacity: subtitleOpacity,
          translate: `0px ${interpolate(subtitleOpacity, [0, 1], [20, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px`,
        }}
      >
        {subtitle}
      </p>
    </AbsoluteFill>
  );
};
