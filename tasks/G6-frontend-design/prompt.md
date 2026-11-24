Design and build the **Meridian Botanical Conservatory — Seasonal Exhibition & Glasshouse Almanac** web application inside `site/` (`site/index.html`, `site/styles.css`, `site/app.js`), powered offline by `site/data/specimens.json`.

Requirements summary:
1. Read `README.md` and inspect `site/data/specimens.json` before designing and building.
2. Build a cohesive visual design tailored to a living botanical conservatory almanac. Ensure responsive layouts across desktop (`1440×900`), tablet (`768×1024`), and mobile (`375×812`) with zero horizontal overflow, `:focus-visible` outlines, and `prefers-reduced-motion` support. Keep all assets 100% self-contained offline (no external CDN scripts, stylesheets, or remote fonts).
3. Implement all required interactive workflows cleanly in `site/app.js`:
   - Fetch `./data/specimens.json`, render all 12 specimen cards, and keep the active Glasshouse Telemetry panel synchronized with the active biome selection.
   - Implement biome filters (`All`, `Cloud Forest`, `Arid Pavilion`, `Alpine House`), live text search, and bloom-season filter with a clear empty state and filter reset control.
   - Implement a keyboard-accessible specimen detail modal/dialog (`Escape` or Close button dismisses it and returns focus to the triggering element).
   - Implement a **Field Guide Comparison Drawer**: allow visitors to add/remove up to 3 specimens from specimen cards via toggle buttons (`data-compare-toggle`), inspect selected specimens side by side inside a comparison drawer/tray (`data-compare-drawer`), and clear selections.
   - Implement the timed-entry visit pass estimator form (visit date, pass tier, visitor count `1–8`) with accessible inline validation errors and live cost calculation summary.
4. Ensure semantic HTML structure, WCAG 2.1 AA accessibility compliance across viewports, and XSS-safe DOM rendering (`textContent`/`createElement`, never raw `innerHTML` with JSON strings).
