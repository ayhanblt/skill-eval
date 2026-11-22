"""AERA/APA/NCME & ETS-aligned Gated Product Scoring + Separate Process Scoring."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from skilleval.schemas import (
    DimensionScore,
    GradeResult,
    JudgeResult,
    RunManifest,
    ScoreCard,
    TraceSummary,
)


def compute_scorecard(
    manifest: RunManifest,
    grade: GradeResult | None,
    trace: TraceSummary | None,
    judge: JudgeResult | None,
    rubric: dict[str, Any],
    task_weights_override: dict[str, float] | None = None,
) -> ScoreCard:
    """Compute gated 0-10 Product Score, separate 0-10 Process Score, and Skill Attribution."""
    prod_cfg = rubric["product_scoring"]
    proc_cfg = rubric["process_scoring"]
    cut_score = float(prod_cfg["pass_cut_score"])
    gate_cap = float(prod_cfg["gate_failure_score_cap"])
    weights: dict[str, float] = dict(task_weights_override or prod_cfg["default_weights"])
    if abs(sum(weights.values()) - float(prod_cfg["scale_max"])) > 1e-6:
        raise ValueError(f"Dimension weights must sum to {prod_cfg['scale_max']}, got {weights}")

    # Collect per-dimension fractions from deterministic grader + blind judge (Jev + visual)
    dim_fractions: dict[str, list[float]] = defaultdict(list)

    if grade is not None:
        for chk in grade.checks:
            if chk.score_fraction is not None:
                dim_fractions[chk.dimension].append(max(0.0, min(1.0, chk.score_fraction)))
            elif chk.passed is not None:
                dim_fractions[chk.dimension].append(1.0 if chk.passed else 0.0)

    if judge is not None:
        for item in (*judge.items, *judge.visual_items):
            if item.score_fraction is None:
                continue
            target_dim = (
                "code_output_maintainability"
                if item.dimension == "visual_design"
                else item.dimension
            )
            dim_fractions[target_dim].append(max(0.0, min(1.0, item.score_fraction)))

    dimensions: list[DimensionScore] = []
    any_missing_weighted = False
    raw_total = 0.0

    for dim_name, weight in weights.items():
        if weight <= 0.0:
            dimensions.append(
                DimensionScore(
                    dimension=dim_name, weight=0.0, earned=0.0, fraction=None, evidence_count=0
                )
            )
            continue
        vals = dim_fractions.get(dim_name, [])
        if not vals:
            any_missing_weighted = True
            dimensions.append(
                DimensionScore(
                    dimension=dim_name, weight=weight, earned=None, fraction=None, evidence_count=0
                )
            )
        else:
            frac = sum(vals) / len(vals)
            earned = round(weight * frac, 3)
            raw_total += earned
            dimensions.append(
                DimensionScore(
                    dimension=dim_name,
                    weight=weight,
                    earned=earned,
                    fraction=round(frac, 4),
                    evidence_count=len(vals),
                )
            )

    gates = grade.gates if grade is not None else GradeResult(run_id=manifest.run_id, task_id=manifest.row.task_id).gates
    raw_product: float | None = None
    product_score: float | None = None
    gate_capped = False
    passed: bool | None = None

    if grade is not None and not any_missing_weighted:
        raw_product = round(min(float(prod_cfg["scale_max"]), raw_total), 2)
        if gates.any_failed:
            product_score = min(raw_product, gate_cap)
            gate_capped = raw_product > gate_cap
            passed = False
        elif gates.all_passed:
            product_score = raw_product
            passed = product_score >= cut_score
        else:
            product_score = raw_product
            passed = None
    elif grade is not None and gates.any_failed:
        # Even if judge is pending, a failed hard gate is definitively FAIL
        passed = False

    # Separate 0-10 Process & Recovery Score
    process_score: float | None = None
    deductions: dict[str, float] = {}
    if trace is not None:
        score = float(proc_cfg["base_score"])
        tax = proc_cfg["error_taxonomy"]
        disc = proc_cfg["discipline_penalties"]

        rec_count = trace.error_counts_by_class.get("recoverable_agent_error", 0)
        if rec_count:
            d = min(
                float(tax["recoverable_agent_error"]["max_penalty_cap"]),
                rec_count * float(tax["recoverable_agent_error"]["penalty"]),
            )
            deductions["recoverable_agent_error"] = round(d, 2)
            score -= d

        rep_count = trace.error_counts_by_class.get("repeated_or_unverified_error", 0)
        if rep_count:
            d = min(
                float(tax["repeated_or_unverified_error"]["max_penalty_cap"]),
                rep_count * float(tax["repeated_or_unverified_error"]["penalty"]),
            )
            deductions["repeated_or_unverified_error"] = round(d, 2)
            score -= d

        if trace.total_edit_calls > 0 and trace.read_steps_before_first_edit == 0:
            d = float(disc["zero_exploration_before_first_edit"])
            deductions["zero_exploration_before_first_edit"] = round(d, 2)
            score -= d

        if trace.total_edit_calls > 0 and not trace.self_verified_after_last_edit:
            d = float(disc["no_verification_after_last_edit"])
            deductions["no_verification_after_last_edit"] = round(d, 2)
            score -= d

        if manifest.status in ("budget_exhausted", "timeout"):
            d = float(disc["budget_exhausted_or_timeout"])
            deductions["budget_exhausted_or_timeout"] = round(d, 2)
            score -= d

        process_score = round(max(0.0, score), 2)

    # Skill behavioral adherence rate
    adherence_rate: float | None = None
    applied_n = 0
    applicable_n = 0
    if trace is not None and trace.probe_outcomes:
        applicable = [p for p in trace.probe_outcomes if p.state != "not_applicable"]
        applicable_n = len(applicable)
        applied_n = sum(1 for p in applicable if p.state == "applied")
        if applicable_n > 0:
            adherence_rate = round(applied_n / applicable_n, 4)

    return ScoreCard(
        run_id=manifest.run_id,
        study_id=manifest.study_id,
        task_id=manifest.row.task_id,
        archetype=manifest.row.archetype,
        condition=manifest.row.condition,
        model=manifest.row.model,
        repeat=manifest.row.repeat,
        status=manifest.status,
        gates=gates,
        raw_product_score=raw_product,
        product_score=product_score,
        gate_capped=gate_capped,
        passed=passed,
        dimensions=dimensions,
        process_score=process_score,
        process_deductions=deductions,
        agent_seconds=manifest.agent_seconds,
        grader_seconds=manifest.grader_seconds,
        tokens=manifest.tokens,
        api_equivalent_cost_usd=manifest.api_equivalent_cost_usd,
        skill_exposure=trace.skill_exposure if trace else "none",
        adherence_rate=adherence_rate,
        adherence_applied=applied_n,
        adherence_applicable=applicable_n,
        infra_error_count=trace.error_counts_by_class.get("infra_sandbox", 0) if trace else 0,
        agent_error_count=(
            trace.error_counts_by_class.get("recoverable_agent_error", 0)
            + trace.error_counts_by_class.get("repeated_or_unverified_error", 0)
        )
        if trace
        else 0,
        read_steps_before_first_edit=trace.read_steps_before_first_edit if trace else 0,
        rework_churn_ratio=trace.rework_churn_ratio if trace else 0.0,
        self_verified_after_last_edit=trace.self_verified_after_last_edit if trace else False,
    )
