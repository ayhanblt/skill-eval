import { zColor } from "@remotion/zod-types";
import { z } from "zod";

export const KpiItemSchema = z.object({
  label: z.string(),
  value: z.string(),
  delta: z.string(),
});

export const BarItemSchema = z.object({
  label: z.string(),
  value: z.number(),
  unit: z.string(),
});

export const CaptionItemSchema = z.object({
  text: z.string(),
  startMs: z.number(),
  endMs: z.number(),
  timestampMs: z.number().nullable(),
  confidence: z.number().nullable(),
});

export const MetricStorySchema = z.object({
  title: z.string(),
  subtitle: z.string(),
  accentColor: zColor(),
  backgroundColor: zColor(),
  sceneDurationsSec: z.array(z.number().positive()).length(4),
  kpis: z.array(KpiItemSchema).min(1),
  bars: z.array(BarItemSchema).min(1),
  takeaway: z.string(),
  cta: z.string(),
  captions: z.array(CaptionItemSchema),
});

export type MetricStoryProps = z.infer<typeof MetricStorySchema>;
export type CaptionItem = z.infer<typeof CaptionItemSchema>;
