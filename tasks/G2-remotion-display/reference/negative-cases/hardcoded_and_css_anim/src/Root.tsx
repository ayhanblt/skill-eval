import React from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Composition, Series, staticFile } from "remotion";

const HardcodedVideo: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#0F172A", padding: 80, color: "#FFFFFF" }}>
      <Audio src={staticFile("narration.wav")} />
      <style>{`@keyframes pulseIn { from { opacity: 0; } to { opacity: 1; } }`}</style>
      <Series>
        <Series.Sequence durationInFrames={90}>
          <h1 style={{ transition: "opacity 0.5s ease", animation: "pulseIn 1s ease" }}>
            Q3 Platform Reliability Report
          </h1>
        </Series.Sequence>
        <Series.Sequence durationInFrames={90}>
          <div>API Availability: 99.98%</div>
        </Series.Sequence>
        <Series.Sequence durationInFrames={90}>
          <div>US-East: 34 ms | EU-Central: 41 ms</div>
        </Series.Sequence>
        <Series.Sequence durationInFrames={90}>
          <div>Edge routing kept latency low.</div>
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  );
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="MetricStory"
      component={HardcodedVideo}
      durationInFrames={360}
      fps={30}
      width={1280}
      height={720}
    />
  );
};
