# Do Agent Skills Really Help? — Experimental Evaluation Report

> **Status:** Study scaffolding in progress. Once the main study (`main-v1`, 216 runs) completes, this file will be generated automatically via `uv run skilleval report --study main-v1`.
>
> - **Turkish Report:** [RAPOR.md](RAPOR.md)
> - **Design & Protocol:** [docs/DESIGN.md](docs/DESIGN.md) · [docs/PROTOCOL.md](docs/PROTOCOL.md)
> - **Interactive HTML Report:** `reports/report.html` *(generated with the study report)*

## Planned Study Overview

| Component | Specification |
|---|---|
| Tasks | 8 deep tasks across 4 skill archetypes (Tool Craft, Workflow Discipline, Production Engineering, Proprietary/Docs-vs-Skill) |
| Models | `claude-sonnet-5-5`, `claude-haiku-5-5` (`effort: medium`) |
| Conditions | `A` (no-skill control), `B` (6 orthogonal skills — passive discovery), `C1` (explicit on-demand invocation), `C2` (4-task always-on system preload ablation) |
| Pre-Freeze Calibration | 32 A-only runs (ceiling-effect gate: target A score 4.0–7.5/10) + Jev anchor calibration |
| Main Matrix | 192 (`A/B/C1`, k=4) + 24 (`C2` ablation, k=3) = **216 runs** |
| Scoring | Gated 0–10 Product Score (7.0 cut score, critical-gate cap ≤ 5.0) + separate 0–10 Process Score + Efficiency Profile + 3-Layer Skill Attribution |
| Blind Evaluation | Atomic 2-pass Jev (`jev-1.14.0`, `≥0.80` probability) + Anonymized Blind Visual & Adjudication UI |
