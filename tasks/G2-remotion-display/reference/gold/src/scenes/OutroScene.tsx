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
  takeaway: string;
  cta: string;
  accentColor: string;
};

export const OutroScene: React.FC<Props> = ({ takeaway, cta, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const cardEnter = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 110 },
  });
  const ctaEnter = interpolate(
    frame,
    [Math.round(0.45 * fps), Math.round(1.1 * fps)],
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
        padding: "80px 110px 140px 110px",
        justifyContent: "center",
        fontFamily: "Liberation Sans, DejaVu Sans, sans-serif",
      }}
    >
      <div
        style={{
          borderLeft: `8px solid ${accentColor}`,
          paddingLeft: 32,
          opacity: cardEnter,
          translate: `0px ${interpolate(cardEnter, [0, 1], [32, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px`,
        }}
      >
        <div
          style={{
            color: accentColor,
            fontSize: 22,
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            marginBottom: 16,
          }}
        >
          Executive Takeaway
        </div>
        <div
          style={{
            color: "#FFFFFF",
            fontSize: 42,
            fontWeight: 700,
            lineHeight: 1.3,
          }}
        >
          {takeaway}
        </div>
      </div>

      <div
        style={{
          marginTop: 42,
          display: "inline-flex",
          alignSelf: "flex-start",
          backgroundColor: accentColor,
          color: "#09111E",
          padding: "16px 28px",
          borderRadius: 10,
          fontSize: 24,
          fontWeight: 800,
          opacity: ctaEnter,
          scale: String(
            interpolate(ctaEnter, [0, 1], [0.94, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          ),
        }}
      >
        {cta}
      </div>
    </AbsoluteFill>
  );
};
