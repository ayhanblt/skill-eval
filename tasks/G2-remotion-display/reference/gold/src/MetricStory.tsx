import React from "react";
import { AbsoluteFill, Series, useVideoConfig } from "remotion";
import type { MetricStoryProps } from "./schema";
import { IntroScene } from "./scenes/IntroScene";
import { KpiScene } from "./scenes/KpiScene";
import { ChartScene } from "./scenes/ChartScene";
import { OutroScene } from "./scenes/OutroScene";
import { CaptionBar } from "./components/CaptionBar";
import { NarrationAudio } from "./components/NarrationAudio";

export const MetricStory: React.FC<MetricStoryProps> = ({
  title,
  subtitle,
  accentColor,
  backgroundColor,
  sceneDurationsSec,
  kpis,
  bars,
  takeaway,
  cta,
  captions,
}) => {
  const { fps } = useVideoConfig();
  const [d1, d2, d3, d4] = sceneDurationsSec;

  return (
    <AbsoluteFill style={{ backgroundColor }}>
      <NarrationAudio />
      <Series>
        <Series.Sequence durationInFrames={Math.round(d1 * fps)}>
          <IntroScene title={title} subtitle={subtitle} accentColor={accentColor} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={Math.round(d2 * fps)}>
          <KpiScene kpis={kpis} accentColor={accentColor} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={Math.round(d3 * fps)}>
          <ChartScene bars={bars} accentColor={accentColor} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={Math.round(d4 * fps)}>
          <OutroScene takeaway={takeaway} cta={cta} accentColor={accentColor} />
        </Series.Sequence>
      </Series>
      <CaptionBar captions={captions} accentColor={accentColor} />
    </AbsoluteFill>
  );
};
