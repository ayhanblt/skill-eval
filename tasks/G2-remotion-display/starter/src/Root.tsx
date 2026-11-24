import React from "react";
import { Composition } from "remotion";

const Placeholder: React.FC = () => {
  return <div style={{ flex: 1, backgroundColor: "#0F172A" }} />;
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="MetricStory"
      component={Placeholder}
      durationInFrames={360}
      fps={30}
      width={1280}
      height={720}
    />
  );
};
