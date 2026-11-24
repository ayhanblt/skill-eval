import React from "react";
import { AbsoluteFill, Composition, Sequence, useCurrentFrame } from "remotion";
import { z } from "zod";

const Schema = z.object({
  title: z.string(),
  subtitle: z.string(),
  accentColor: z.string(),
  backgroundColor: z.string(),
  sceneDurationsSec: z.array(z.number().positive()).length(4).optional(),
  kpis: z.array(z.object({ label: z.string(), value: z.string(), delta: z.string() })),
  bars: z.array(z.object({ label: z.string(), value: z.number(), unit: z.string() })),
  takeaway: z.string(),
  cta: z.string(),
  captions: z.array(
    z.object({
      text: z.string(),
      startMs: z.number(),
      endMs: z.number(),
      timestampMs: z.number().nullable(),
      confidence: z.number().nullable(),
    }),
  ),
});

const StaticStory: React.FC<z.infer<typeof Schema>> = (props) => {
  useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: props.backgroundColor, color: "#fff", padding: 80 }}>
      <Sequence durationInFrames={360}>
        <h1>{props.title}</h1>
        <p>{props.subtitle}</p>
      </Sequence>
    </AbsoluteFill>
  );
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="MetricStory"
    component={StaticStory}
    durationInFrames={360}
    fps={30}
    width={1280}
    height={720}
    schema={Schema}
    defaultProps={{
      title: "Q3 Platform Reliability Report",
      subtitle: "Production Latency, Availability & Edge Delivery",
      accentColor: "#38BDF8",
      backgroundColor: "#0F172A",
      sceneDurationsSec: [3, 3, 3, 3],
      kpis: [{ label: "API Availability", value: "99.98%", delta: "+0.04%" }],
      bars: [{ label: "US-East", value: 34, unit: "ms" }],
      takeaway: "Takeaway",
      cta: "CTA",
      captions: [],
    }}
  />
);
