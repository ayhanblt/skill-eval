"""Bilingual report generator (root RAPOR.md / REPORT.md + interactive HTML + CSV/JSON)."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from html import escape
from pathlib import Path
from statistics import mean, median
from typing import Any

from skilleval.config import load_study_spec
from skilleval.runner import score_study, study_dir
from skilleval.schemas import ScoreCard


def _fmt_num(val: float | None, decimals: int = 2, suffix: str = "") -> str:
    if val is None:
        return "—"
    return f"{val:.{decimals}f}{suffix}"


def _pass_pow_k(cards: list[ScoreCard]) -> tuple[int, int]:
    """Compute tau-bench pass^k consistency across (task, model) cells."""
    by_cell: dict[tuple[str, str], list[ScoreCard]] = defaultdict(list)
    for c in cards:
        by_cell[(c.task_id, c.model)].append(c)
    consistent = sum(
        1 for group in by_cell.values() if group and all(c.passed is True for c in group)
    )
    return consistent, len(by_cell)


def _summarize_group(cards: list[ScoreCard]) -> dict[str, Any]:
    scored = [c.product_score for c in cards if c.product_score is not None]
    proc = [c.process_score for c in cards if c.process_score is not None]
    secs = [c.agent_seconds for c in cards if c.agent_seconds is not None]
    costs = [c.api_equivalent_cost_usd for c in cards if c.api_equivalent_cost_usd is not None]
    adh = [c.adherence_rate for c in cards if c.adherence_rate is not None]
    passed = sum(1 for c in cards if c.passed is True)
    evaluated = sum(1 for c in cards if c.passed is not None)
    pk_hit, pk_total = _pass_pow_k(cards)
    total_cost = sum(costs) if costs else None
    cost_per_pass = (total_cost / passed) if (total_cost is not None and passed > 0) else None
    return {
        "n": len(cards),
        "passed": passed,
        "evaluated": evaluated,
        "pass_rate": (100.0 * passed / evaluated) if evaluated else None,
        "pass_pow_k": f"{pk_hit}/{pk_total}" if pk_total else "—",
        "avg_product": mean(scored) if scored else None,
        "avg_process": mean(proc) if proc else None,
        "median_seconds": median(secs) if secs else None,
        "total_cost_usd": total_cost,
        "cost_per_pass_usd": cost_per_pass,
        "avg_adherence": (100.0 * mean(adh)) if adh else None,
        "infra_errors": sum(c.infra_error_count for c in cards),
        "agent_errors": sum(c.agent_error_count for c in cards),
        "avg_reads_before_edit": mean(c.read_steps_before_first_edit for c in cards) if cards else None,
        "self_verified_pct": (
            100.0 * sum(1 for c in cards if c.self_verified_after_last_edit) / len(cards)
            if cards
            else None
        ),
    }


def _render_markdown(
    lang: str,
    study_id: str,
    spec: dict[str, Any],
    cards: list[ScoreCard],
) -> str:
    is_tr = lang == "tr"
    by_cond: dict[str, list[ScoreCard]] = defaultdict(list)
    by_task: dict[str, list[ScoreCard]] = defaultdict(list)
    by_model_cond: dict[tuple[str, str], list[ScoreCard]] = defaultdict(list)
    for c in cards:
        by_cond[c.condition].append(c)
        by_task[c.task_id].append(c)
        by_model_cond[(c.model, c.condition)].append(c)

    title = (
        f"# Agent Skills Gerçekten İşe Yarıyor mu? (`{study_id}`)"
        if is_tr
        else f"# Do Agent Skills Really Help? (`{study_id}`)"
    )
    other_link = (
        "[English Report](REPORT.md) · [Etkileşimli HTML](reports/rapor.html) · [Tasarım](docs/DESIGN.md)"
        if is_tr
        else "[Türkçe Rapor](RAPOR.md) · [Interactive HTML](reports/report.html) · [Design](docs/DESIGN.md)"
    )

    lines = [title, "", other_link, ""]
    if not cards:
        lines.append(
            "_Henüz tamamlanmış koşu yok. `uv run skilleval run --study "
            f"{study_id}` sonrasında bu rapor gerçek verilerle dolacaktır._"
            if is_tr
            else f"_No completed runs yet. Run `uv run skilleval run --study {study_id}` to populate._"
        )
        return "\n".join(lines) + "\n"

    # 1. Condition summary table
    lines.append("## Koşullara Göre Özet" if is_tr else "## Summary by Condition")
    lines.append("")
    if is_tr:
        lines.append(
            "| Koşul | Geçme (ETS ≥7.0 & Kapılar) | `pass^k` | Ürün Puanı (/10) | Süreç Puanı (/10) | "
            "Yönerge Uygulama | Ortanca Süre | API Eşdeğeri | Başarı Başı Maliyet |"
        )
    else:
        lines.append(
            "| Condition | Pass Rate (ETS ≥7.0 & Gates) | `pass^k` | Product (/10) | Process (/10) | "
            "Skill Adherence | Median Time | API-Equiv Cost | Cost / Pass |"
        )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for cond in ("A", "B", "C1", "C2"):
        if cond not in by_cond:
            continue
        s = _summarize_group(by_cond[cond])
        lines.append(
            f"| **{cond}** | {s['passed']}/{s['evaluated']} ({_fmt_num(s['pass_rate'], 1, '%')}) | "
            f"{s['pass_pow_k']} | {_fmt_num(s['avg_product'])} | {_fmt_num(s['avg_process'])} | "
            f"{_fmt_num(s['avg_adherence'], 1, '%')} | {_fmt_num(s['median_seconds'], 1, 's')} | "
            f"${_fmt_num(s['total_cost_usd'], 3)} | ${_fmt_num(s['cost_per_pass_usd'], 3)} |"
        )

    # 2. Task-level breakdown
    lines.extend(["", "## Görev Bazında Ürün & Süreç Puanları" if is_tr else "## Per-Task Product & Process Scores", ""])
    lines.append(
        "| Görev | Arketip | A | B | C1 | C2 | B Hedef Skill Erişimi |"
        if is_tr
        else "| Task | Archetype | A | B | C1 | C2 | B Target Discovery |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for task in spec["tasks"]:
        tid = task["id"]
        tcards = by_task.get(tid, [])
        vals = {}
        for cond in ("A", "B", "C1", "C2"):
            sub = [c for c in tcards if c.condition == cond]
            if not sub:
                vals[cond] = "—"
            else:
                s = _summarize_group(sub)
                vals[cond] = f"{_fmt_num(s['avg_product'])} ({s['passed']}/{s['evaluated']})"
        b_cards = [c for c in tcards if c.condition == "B"]
        b_disc = (
            f"{sum(1 for c in b_cards if c.skill_exposure in ('invoked_target', 'references_read'))}/{len(b_cards)}"
            if b_cards
            else "—"
        )
        lines.append(
            f"| `{tid}` | `{task['archetype']}` | {vals['A']} | {vals['B']} | {vals['C1']} | {vals['C2']} | {b_disc} |"
        )

    # 3. Model x Condition ("Haiku + Skill vs Sonnet No-Skill")
    lines.extend(["", "## Model × Koşul Karşılaştırması" if is_tr else "## Model × Condition Breakdown", ""])
    lines.append(
        "| Model | Koşul | Ürün (/10) | Süreç (/10) | Geçme | Keşif-Önce Adım | Öz-Doğrulama |"
        if is_tr
        else "| Model | Condition | Product (/10) | Process (/10) | Pass | Explore-Before-Edit | Self-Verified |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for (model, cond), group in sorted(by_model_cond.items()):
        s = _summarize_group(group)
        lines.append(
            f"| `{model}` | **{cond}** | {_fmt_num(s['avg_product'])} | {_fmt_num(s['avg_process'])} | "
            f"{s['passed']}/{s['evaluated']} | {_fmt_num(s['avg_reads_before_edit'], 1)} | "
            f"{_fmt_num(s['self_verified_pct'], 1, '%')} |"
        )

    return "\n".join(lines) + "\n"


def _render_html(lang: str, study_id: str, spec: dict[str, Any], cards: list[ScoreCard]) -> str:
    is_tr = lang == "tr"
    title = (
        f"Skill-Eval · {study_id} Etkileşimli Araştırma Raporu"
        if is_tr
        else f"Skill-Eval · {study_id} Interactive Evaluation Report"
    )
    rows_html = []
    for c in sorted(cards, key=lambda x: (x.task_id, x.condition, x.model, x.repeat)):
        badge = "PASS" if c.passed is True else ("FAIL" if c.passed is False else "PENDING")
        rows_html.append(
            "<tr>"
            f"<td><code>{escape(c.run_id)}</code></td>"
            f"<td>{escape(c.task_id)}</td>"
            f"<td><strong>{escape(c.condition)}</strong></td>"
            f"<td>{escape(c.model)}</td>"
            f"<td>{c.repeat}</td>"
            f"<td><strong>{_fmt_num(c.product_score)}</strong>{' (cap)' if c.gate_capped else ''}</td>"
            f"<td>{badge}</td>"
            f"<td>{_fmt_num(c.process_score)}</td>"
            f"<td>{escape(c.skill_exposure)}</td>"
            f"<td>{_fmt_num(c.adherence_rate * 100 if c.adherence_rate is not None else None, 0, '%')}</td>"
            f"<td>{c.agent_error_count} / {c.infra_error_count}</td>"
            f"<td>{_fmt_num(c.agent_seconds, 1, 's')}</td>"
            f"<td>${_fmt_num(c.api_equivalent_cost_usd, 3)}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
:root {{ font: 15px/1.55 system-ui, -apple-system, sans-serif; color: #13212c; background: #eef3f6; }}
main {{ max-width: 1260px; margin: 24px auto; padding: 0 18px 60px; }}
header {{ background: #102b32; color: #f1fdfb; padding: 24px 28px; border-radius: 14px; margin-bottom: 18px; }}
section {{ background: #fff; border: 1px solid #d5e0e6; border-radius: 12px; padding: 20px; margin-bottom: 16px; overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e3ebf0; white-space: nowrap; }}
th {{ background: #f3f7f9; position: sticky; top: 0; }}
</style>
</head>
<body>
<main>
  <header>
    <h1 style="margin:0 0 6px;">{escape(title)}</h1>
    <p style="margin:0;opacity:.85;">{'AERA/APA/NCME & ETS uyumlu Kapılı Ürün Puanı, Süreç Puanı, Hata Taksonomisi ve 3 Katmanlı Skill İzleme' if is_tr else 'AERA/APA/NCME & ETS-aligned Gated Product Score, Process Score, Error Taxonomy & 3-Layer Skill Attribution'}</p>
  </header>
  <section>
    <h2>{'Tüm Koşular' if is_tr else 'All Runs'} ({len(cards)})</h2>
    <table>
      <thead>
        <tr>
          <th>Run</th><th>Task</th><th>Cond</th><th>Model</th><th>Rep</th>
          <th>Product (/10)</th><th>Verdict</th><th>Process (/10)</th>
          <th>Skill Exposure</th><th>Adherence</th><th>Err (Agent/Infra)</th>
          <th>Agent Time</th><th>API Equiv</th>
        </tr>
      </thead>
      <tbody>{''.join(rows_html) or '<tr><td colspan="13">No runs recorded yet.</td></tr>'}</tbody>
    </table>
  </section>
</main>
</body>
</html>
"""


def generate_reports(root: Path, study_id: str) -> dict[str, Path]:
    spec = load_study_spec(root)
    cards = score_study(root, study_id)
    sdir = study_dir(root, study_id)
    sdir.mkdir(parents=True, exist_ok=True)
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Export flat JSON & CSV dataset
    ds_json = sdir / "dataset.json"
    ds_json.write_text(
        json.dumps([c.model_dump(mode="json") for c in cards], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    ds_csv = sdir / "dataset.csv"
    fieldnames = [
        "run_id", "study_id", "task_id", "archetype", "condition", "model", "repeat",
        "status", "passed", "raw_product_score", "product_score", "gate_capped",
        "process_score", "skill_exposure", "adherence_rate", "agent_error_count",
        "infra_error_count", "read_steps_before_first_edit", "rework_churn_ratio",
        "self_verified_after_last_edit", "agent_seconds", "grader_seconds",
        "api_equivalent_cost_usd",
    ]
    with ds_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for c in cards:
            row = c.model_dump(mode="json")
            writer.writerow({k: row.get(k) for k in fieldnames})

    # Write root bilingual Markdown + interactive HTML
    tr_md = root / "RAPOR.md"
    en_md = root / "REPORT.md"
    tr_html = reports_dir / "rapor.html"
    en_html = reports_dir / "report.html"

    tr_md.write_text(_render_markdown("tr", study_id, spec, cards), encoding="utf-8")
    en_md.write_text(_render_markdown("en", study_id, spec, cards), encoding="utf-8")
    tr_html.write_text(_render_html("tr", study_id, spec, cards), encoding="utf-8")
    en_html.write_text(_render_html("en", study_id, spec, cards), encoding="utf-8")

    return {
        "rapor_md": tr_md,
        "report_md": en_md,
        "rapor_html": tr_html,
        "report_html": en_html,
        "dataset_csv": ds_csv,
        "dataset_json": ds_json,
    }
