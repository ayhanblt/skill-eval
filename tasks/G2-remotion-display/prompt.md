Build a data-driven, 4-scene Remotion video composition (`MetricStory`) suitable for interactive Remotion Studio editing and render the final video to `out/video.mp4` using `props/dataset_a.json`.

Requirements summary:
1. Inspect `README.md`, `package.json`, `props/dataset_a.json`, and `public/narration.wav` before starting. Do NOT run `npm install` (dependencies are already installed in `node_modules`).
2. Register composition ID `MetricStory` in `src/Root.tsx` at `1280x720`, `30 fps`, whose schema enables visual color picking in Remotion Studio and whose total frame duration adapts dynamically from `props.sceneDurationsSec` (12 seconds = `360` frames for `dataset_a.json`, and arbitrary positive 4-element durations under alternate `--props`).
3. Build the 4 sequential scenes (`Intro`, `KPI Cards`, `Bar Chart`, `Takeaway & CTA`) timed proportionally to `sceneDurationsSec[0..3]` with smooth, Studio-editable motion and scoped frame updates (no monolithic root re-renders or CSS transitions).
4. Include `public/narration.wav` with smooth fade-in (~0.5–0.6 s at start) and fade-out (~0.5–0.6 s at end) audio envelope, plus bottom captions synchronized to `props.captions` (`startMs`/`endMs`, handling empty captions cleanly), remaining 100% self-contained offline across custom `--props` payloads (`2–6` bars, custom colors/durations).
5. Verify TypeScript (`npx tsc --noEmit`) and render `out/video.mp4` from `props/dataset_a.json`.
