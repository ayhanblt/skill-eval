import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type Kpi = { label: string; value: string; delta: string };

type Props = {
  kpis: readonly Kpi[];
  accentColor: string;
};

export const KpiScene: React.FC<Props> = ({ kpis, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headerOpacity = interpolate(frame, [0, Math.round(0.4 * fps)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  return (
    <AbsoluteFill
      style={{
        padding: "76px 90px 130px 90px",
        fontFamily: "Liberation Sans, DejaVu Sans, sans-serif",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          color: accentColor,
          fontSize: 22,
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          marginBottom: 24,
          opacity: headerOpacity,
        }}
      >
        Key Performance Indicators
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${Math.min(3, kpis.length)}, 1fr)`,
          gap: 28,
        }}
      >
        {kpis.map((item, idx) => {
          const delay = Math.round(idx * 0.25 * fps);
          const enter = spring({
            frame: Math.max(0, frame - delay),
            fps,
            config: { damping: 16, stiffness: 130 },
          });
          return (
            <div
              key={item.label}
              style={{
                backgroundColor: "rgba(255, 255, 255, 0.06)",
                border: `2px solid ${accentColor}`,
                borderRadius: 16,
                padding: "32px 28px",
                opacity: enter,
                scale: String(
                  interpolate(enter, [0, 1], [0.9, 1], {
                    extrapolateLeft: "clamp",
                    extrapolateRight: "clamp",
                  }),
                ),
                translate: `0px ${interpolate(enter, [0, 1], [28, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px`,
              }}
            >
              <div style={{ color: "#CBD5E1", fontSize: 22, fontWeight: 600 }}>
                {item.label}
              </div>
              <div
                style={{
                  color: "#FFFFFF",
                  fontSize: 54,
                  fontWeight: 800,
                  margin: "16px 0 12px 0",
                }}
              >
                {item.value}
              </div>
              <div style={{ color: accentColor, fontSize: 22, fontWeight: 700 }}>
                {item.delta}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
