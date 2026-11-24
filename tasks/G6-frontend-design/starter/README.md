# Meridian Botanical Conservatory — Product & Engineering Brief

Build the static offline web application in `site/`:
- `site/index.html`
- `site/styles.css`
- `site/app.js`
- Data source (provided): `site/data/specimens.json`

## Functional Contract

1. **Dynamic Specimen Almanac & Biome Telemetry**:
   - Load `./data/specimens.json` on startup (`fetch('./data/specimens.json')`).
   - Render all 12 specimen items inside `<main>`. Mark each specimen card element with `data-specimen-card` displaying common name, Latin binomial, biome, bloom season, summary, inspect trigger button, and field-guide comparison toggle (`data-compare-toggle`).
   - Render a **Glasshouse Telemetry** panel showing climate metrics (`temperature_c`, `humidity_pct`, `misting_schedule`, `architectural_note`) from `specimens.json.biomes`, updating dynamically when a biome filter is chosen.
2. **Biome Filter, Search, Bloom Filter & Empty State**:
   - Provide accessible filter buttons for `All`, `Cloud Forest`, `Arid Pavilion`, and `Alpine House` (with `aria-pressed`).
   - Provide a labeled search `<input type="search">` and bloom season `<select>` filter.
   - When filters yield 0 matches, render a visible empty-state panel with `data-empty-state` and a reset button returning all 12 specimens.
3. **Accessible Specimen Detail Dialog**:
   - Activating a specimen card opens a `<dialog>` or `role="dialog"` (`aria-modal="true"`) displaying the specimen's Latin name, origin elevation, conservation status, and full care notes.
   - Pressing `Escape` or activating the Close button closes the dialog and returns focus to the triggering button.
4. **Field Guide Comparison Drawer (`[data-compare-drawer]`)**:
   - Each card includes a comparison toggle button (`data-compare-toggle`, `aria-pressed`) allowing up to 3 specimens to be pinned for side-by-side study.
   - Render selected specimens side-by-side inside `[data-compare-drawer]` (showing biome, elevation, bloom season, and conservation status), along with a clear/reset control (`data-compare-clear` or labeled clear button) to empty the comparison selection.
5. **Timed-Entry Visit Pass Estimator (`<form>`)**:
   - Labeled controls for visit date (`<input type="date">`), pass tier (`<select>` populated from `specimens.json.visitPasses`), and visitor count (`<input type="number">` min 1, max 8).
   - Submitting empty/invalid inputs displays an accessible inline validation message (`role="alert"`).
   - Submitting valid inputs renders a live confirmation summary (`data-pass-summary`) showing tier name, visitor count, and computed total (`visitors * priceUsd`).
6. **Engineering & Accessibility Requirements**:
   - Zero external network requests (offline sandbox).
   - Semantic landmarks (`<header>`, `<nav>`, `<main>`), single `<h1>`, `:focus-visible`, `@media (prefers-reduced-motion: reduce)`, WCAG 2.1 AA contrast, and zero horizontal overflow at `1440×900`, `768×1024`, and `375×812`.
   - XSS-safe DOM updates: use `textContent` / `createElement` for all JSON data.
