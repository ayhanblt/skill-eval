import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type Bar = { label: string; value: number; unit: string };

type Props = {
  bars: readonly Bar[];
  accentColor: string;
};

export const ChartScene: React.FC<Props> = ({ bars, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const maxValue = Math.max(1, ...bars.map((b) => b.value));
  const titleOpacity = interpolate(frame, [0, Math.round(0.4 * fps)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const titleY = interpolate(frame, [0, Math.round(0.4 * fps)], [16, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  return (
    <AbsoluteFill
      style={{
        padding: "68px 100px 136px 100px",
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
          marginBottom: 28,
          opacity: titleOpacity,
          translate: `0px ${titleY}px`,
        }}
      >
        Regional Breakdown
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
        {bars.map((bar, idx) => {
          const delay = Math.round(idx * 0.18 * fps);
          const grow = spring({
            frame: Math.max(0, frame - delay),
            fps,
            config: { damping: 20, stiffness: 100 },
          });
          const pct = (bar.value / maxValue) * 100 * grow;

          return (
            <div
              key={bar.label}
              style={{
                display: "grid",
                gridTemplateColumns: "210px 1fr 140px",
                alignItems: "center",
                gap: 20,
              }}
            >
              <div style={{ color: "#F8FAFC", fontSize: 24, fontWeight: 600 }}>
                {bar.label}
              </div>
              <div
                style={{
                  height: 36,
                  backgroundColor: "rgba(255,255,255,0.09)",
                  borderRadius: 8,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: `${pct}%`,
                    backgroundColor: accentColor,
                    borderRadius: 8,
                  }}
                />
              </div>
              <div
                style={{
                  color: "#E2E8F0",
                  fontSize: 24,
                  fontWeight: 700,
                  textAlign: "right",
                }}
              >
                {Math.round(bar.value * grow)} {bar.unit}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
