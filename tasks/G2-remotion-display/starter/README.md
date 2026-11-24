# MetricStory — Video Product Specification

Build and render a Studio-editable, parametric data-storytelling video (`MetricStory`, `1280x720`, `30 fps`) rendered to `out/video.mp4` from `props/dataset_a.json`.

## Input Props Contract (`props/dataset_a.json`)

The registered `MetricStory` composition must accept typed props matching this exact JSON shape with a schema suitable for Remotion Studio sidebar parameter editing (including visual color pickers for `accentColor` and `backgroundColor`):

```json
{
  "title": "string",
  "subtitle": "string",
  "accentColor": "#38BDF8",
  "backgroundColor": "#0F172A",
  "sceneDurationsSec": [3, 3, 3, 3],
  "kpis": [{ "label": "string", "value": "string", "delta": "string" }],
  "bars": [{ "label": "string", "value": 34, "unit": "ms" }],
  "takeaway": "string",
  "cta": "string",
  "captions": [
    { "text": "string", "startMs": 0, "endMs": 3000, "timestampMs": 1500, "confidence": 0.99 }
  ]
}
```

## Timeline & Behavior Requirements

1. **Dynamic Multi-Scene Timeline (`sceneDurationsSec`)**:
   - Compute total video duration dynamically from `sceneDurationsSec` (`sum(sceneDurationsSec)` seconds at `30 fps`) so alternative `--props` JSON files with different 4-element `sceneDurationsSec` arrays (e.g., `[2, 4, 4, 4]` = 14 seconds) automatically render at that exact duration rather than a hardcoded 12s/`360`-frame length.
   - Sequence the 4 scenes cleanly using `sceneDurationsSec[0..3]`:
     - **Scene 1**: Animated title & subtitle reveal styled with `backgroundColor` and `accentColor`.
     - **Scene 2**: Staggered animated KPI cards rendered from `props.kpis`.
     - **Scene 3**: Animated data bar chart scaled cleanly from `props.bars` (must handle `2` to `6` bars cleanly without overflow or division by zero).
     - **Scene 4**: Key takeaway & call-to-action outro (`props.takeaway`, `props.cta`).
2. **Synchronized Audio Fade & Captions**:
   - Play `public/narration.wav` inside the composition with a smooth fade-in over the opening ~0.5–0.6 seconds and fade-out over the closing ~0.5–0.6 seconds.
   - Render a readable bottom caption overlay showing the active entry from `props.captions` while `startMs <= currentTimeMs && currentTimeMs < endMs` (gracefully rendering nothing when `captions` is empty).
3. **Production Engineering Constraints**:
   - Structure components modularly under `src/`, keeping per-frame subscriptions scoped to leaf components so the root composition container does not re-render every frame.
   - Keep animations Studio-editable and deterministic (avoiding CSS transitions/animations) and keep rendering 100% offline (zero `http://` or `https://` requests).
4. **Deliverable**:
   - `npx tsc --noEmit` exits `0`.
   - Render `out/video.mp4` via `npx remotion render MetricStory out/video.mp4 --props=props/dataset_a.json`.
