"""Core unit tests for skilleval invariants, error taxonomy, scoring, capture, and reporting."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skilleval.capture import render_transcript_markdown
from skilleval.config import (
    NON_DISTRACTOR_SKILLS,
    build_matrix,
    load_rubric_spec,
    project_root,
    render_user_prompt,
    resolve_orthogonal_distractors,
)
from skilleval.schemas import (
    CheckOutcome,
    GateResults,
    GradeResult,
    JudgeItemResult,
    JudgeResult,
    MatrixRow,
    RunManifest,
    TokenUsage,
)
from skilleval.scoring import compute_scorecard
from skilleval.trace_analyzer import analyze_trace


def _sample_manifest(condition: str = "C1", target_skill: str = "test-driven-development") -> RunManifest:
    row = MatrixRow(
        run_id="RUN-001",
        study_id="main-v1",
        phase="main",
        task_id="G4-tdd-feature",
        archetype="workflow_discipline",
        target_skill=target_skill,
        condition=condition,  # type: ignore[arg-type]
        model="claude-sonnet-5-5",
        repeat=1,
        installed_skills=[target_skill, "xlsx", "pdf", "frontend-design", "remotion-best-practices", "supabase-postgres-best-practices"]
        if condition in ("B", "C1")
        else [],
        preload_skill=target_skill if condition == "C2" else None,
    )
    return RunManifest(
        run_id="RUN-001",
        study_id="main-v1",
        attempt_id="attempt-1",
        row=row,
        status="completed",
        started_utc=datetime.now(UTC),
        ended_utc=datetime.now(UTC),
        agent_seconds=42.5,
        exit_code=0,
        terminal_subtype="success",
        actual_models=["claude-sonnet-5-5"],
        tokens=TokenUsage(input_tokens=1000, cache_read_input_tokens=5000, output_tokens=800),
        api_equivalent_cost_usd=0.0165,
    )


def test_matrix_counts_and_orthogonality() -> None:
    root = project_root(Path(__file__).resolve().parent)

    cal = build_matrix(root, "calibration-v1")
    assert len(cal) == 32
    assert {r.condition for r in cal} == {"A"}

    main = build_matrix(root, "main-v1")
    assert len(main) == 216
    counts = Counter(r.condition for r in main)
    assert counts == {"A": 64, "B": 64, "C1": 64, "C2": 24}

    for row in main:
        if row.condition in ("B", "C1"):
            assert len(row.installed_skills) == 6
            assert row.target_skill in row.installed_skills
            distractors = set(row.installed_skills) - {row.target_skill}
            # Critical invariant: discipline skills NEVER appear as distractors!
            assert not (distractors & NON_DISTRACTOR_SKILLS)
        elif row.condition == "A":
            assert row.installed_skills == []
            assert row.preload_skill is None
        elif row.condition == "C2":
            assert row.installed_skills == []
            assert row.preload_skill == row.target_skill


def test_distractor_validator_blocks_spillover() -> None:
    bad_registry = {
        "skills": {"a": {"domain": "x"}, "systematic-debugging": {"domain": "y"}},
        "task_distractors": {"T": ["systematic-debugging", "b", "c", "d", "e"]},
    }
    with pytest.raises(ValueError, match="non-orthogonal discipline"):
        resolve_orthogonal_distractors("T", "a", bad_registry, count=5)


def test_prompt_policy_c2_matches_a_and_b() -> None:
    base = "Implement feature X."
    assert render_user_prompt(base, "A", "xlsx") == render_user_prompt(base, "B", "xlsx")
    assert render_user_prompt(base, "A", "xlsx") == render_user_prompt(base, "C2", "xlsx")
    c1 = render_user_prompt(base, "C1", "xlsx")
    assert "invoke the `xlsx` skill" in c1


def test_error_taxonomy_and_tdd_detection(tmp_path: Path) -> None:
    root = project_root(Path(__file__).resolve().parent)
    manifest = _sample_manifest(condition="C1", target_skill="test-driven-development")

    events = [
        {"type": "system", "subtype": "init", "skills": ["test-driven-development", "xlsx"], "tools": ["Read", "Bash", "Edit", "Skill"]},
        # 1. Read + invoke skill before edit
        {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/workspace/app.py"}},
            {"type": "tool_use", "id": "t2", "name": "Skill", "input": {"skill": "test-driven-development"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": False, "content": "def price(): return 0"},
            {"type": "tool_result", "tool_use_id": "t2", "is_error": False, "content": "TDD guidance loaded"},
        ]}},
        # 2. Sandbox .gitconfig error -> MUST be infra_sandbox (0 penalty!)
        {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [
            {"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "git status"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t3", "is_error": True, "content": "fatal: unable to access '/Users/x/.gitconfig': Operation not permitted"},
        ]}},
        # 3. Write test + run pytest RED assertion before production edit -> expected_negative (0 penalty!)
        {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [
            {"type": "tool_use", "id": "t4", "name": "Write", "input": {"file_path": "/workspace/test_app.py"}},
            {"type": "tool_use", "id": "t5", "name": "Bash", "input": {"command": "pytest test_app.py"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t4", "is_error": False, "content": "ok"},
            {"type": "tool_result", "tool_use_id": "t5", "is_error": True, "content": "AssertionError: assert 0 == 100"},
        ]}},
        # 4. Edit production file + run pytest GREEN
        {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [
            {"type": "tool_use", "id": "t6", "name": "Edit", "input": {"file_path": "/workspace/app.py"}},
            {"type": "tool_use", "id": "t7", "name": "Bash", "input": {"command": "pytest test_app.py"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t6", "is_error": False, "content": "ok"},
            {"type": "tool_result", "tool_use_id": "t7", "is_error": False, "content": "1 passed"},
        ]}},
    ]
    sess = tmp_path / "session.jsonl"
    sess.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    patch = tmp_path / "workspace.patch"
    patch.write_text("+def test_basic():\n+    assert price() == 100\n", encoding="utf-8")
    transcript = tmp_path / "transcript.md"
    transcript.write_text(render_transcript_markdown(manifest, "Build pricing", sess), encoding="utf-8")

    trace = analyze_trace(
        manifest,
        sess,
        patch_path=patch,
        transcript_path=transcript,
        probes_path=root / "skills" / "test-driven-development" / "probes.yaml",
    )
    assert trace.error_counts_by_class["infra_sandbox"] == 1
    assert trace.error_counts_by_class["expected_negative"] == 1
    assert trace.error_counts_by_class["recoverable_agent_error"] == 0
    assert trace.tdd_red_before_green is True
    assert trace.self_verified_after_last_edit is True
    assert trace.skill_exposure == "invoked_target"
    assert all(p.state == "applied" for p in trace.probe_outcomes)

    # Now verify Gated Product Scoring vs Process Scoring
    rubric = load_rubric_spec(root)
    grade_pass = GradeResult(
        run_id="RUN-001",
        task_id="G4-tdd-feature",
        gates=GateResults(G1_CONTRACT_BUILD=True, G2_CRITICAL_CORRECTNESS=True, G3_CRITICAL_SAFETY_RULES=True),
        checks=[
            CheckOutcome(id="c1", dimension="correctness_completeness", critical=True, passed=True),
            CheckOutcome(id="c2", dimension="robustness_edge_cases", passed=True),
            CheckOutcome(id="c3", dimension="test_tdd_quality", passed=True),
            CheckOutcome(id="c4", dimension="solution_performance_security", passed=True),
        ],
    )
    judge_pass = JudgeResult(
        run_id="RUN-001",
        blind_code="abcd1234",
        judge_model="jev-1.14.0",
        items=[
            JudgeItemResult(
                item_id="j1",
                dimension="code_output_maintainability",
                question="Clean code?",
                value="pass",
                score_fraction=1.0,
                source="jev",
            )
        ],
        complete=True,
    )
    card = compute_scorecard(manifest, grade_pass, trace, judge_pass, rubric)
    assert card.product_score == 10.0
    assert card.passed is True
    assert card.process_score == 10.0  # Infra & TDD red errors incur ZERO penalty!

    # Critical gate failure MUST cap visible product score <= 5.0 and force passed=False
    grade_gate_fail = grade_pass.model_copy(
        update={
            "gates": GateResults(
                G1_CONTRACT_BUILD=True,
                G2_CRITICAL_CORRECTNESS=False,
                G3_CRITICAL_SAFETY_RULES=True,
            )
        }
    )
    capped_card = compute_scorecard(manifest, grade_gate_fail, trace, judge_pass, rubric)
    assert capped_card.raw_product_score == 10.0
    assert capped_card.product_score == 5.0
    assert capped_card.gate_capped is True
    assert capped_card.passed is False
