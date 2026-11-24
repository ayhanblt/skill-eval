"""Core unit tests for skilleval invariants, error taxonomy, scoring, capture, and reporting."""

from __future__ import annotations

import json
import ssl
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skilleval.capture import render_transcript_markdown
from skilleval.config import (
    NON_DISTRACTOR_SKILLS,
    build_matrix,
    load_rubric_spec,
    load_study_spec,
    project_root,
    render_user_prompt,
    resolve_orthogonal_distractors,
)
from skilleval.judge import (
    JevTokenLimitError,
    MAX_BLIND_STATE_CHARS,
    _build_ssl_context,
    _format_blind_state,
    _strip_binary_git_patches,
    evaluate_state_with_jev,
)
from skilleval.review_ui import generate_blind_review_ui
from skilleval.runner import _detect_auth_failure, _extract_result_is_error, _models_match_requested
from skilleval.sandbox import _build_claude_settings, _build_ephemeral_auth_wrapper
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

    cal3 = build_matrix(root, "calibration-v3")
    assert len(cal3) == 12
    assert {r.condition for r in cal3} == {"A"}
    assert {r.task_id for r in cal3} == {
        "G2-remotion-display",
        "G3-systematic-debugging",
        "G4-tdd-feature",
    }

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


def test_sandbox_settings_and_runner_guards(tmp_path: Path) -> None:
    row_a = _sample_manifest(condition="A").row
    row_b = _sample_manifest(condition="B").row
    settings_a = _build_claude_settings(row_a)
    settings_b = _build_claude_settings(row_b)

    for builtin in ("Skill(design)", "Skill(doctor)", "Skill(plugin-authoring)"):
        assert builtin in settings_a["permissions"]["deny"]
        assert builtin in settings_b["permissions"]["deny"]
    assert "Skill" in settings_a["permissions"]["deny"]
    assert "Skill" not in settings_a["permissions"]["allow"]
    assert "Skill" not in settings_b["permissions"]["deny"]
    assert "Skill" in settings_b["permissions"]["allow"]

    assert _models_match_requested("claude-sonnet-5-5", ["claude-sonnet-5-5"]) is True
    assert _models_match_requested("claude-sonnet-5-5", ["claude-sonnet-5-5-20260929"]) is True
    assert _models_match_requested("claude-sonnet-5-5", ["claude-haiku-5-5"]) is False

    err_sess = tmp_path / "err_session.jsonl"
    err_sess.write_text(
        "\n".join(
            [
                json.dumps({"type": "assistant", "error": "authentication_failed"}),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": True,
                        "result": "Not logged in · Please run /login",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert _detect_auth_failure(err_sess, "") == "authentication_failed"
    assert _extract_result_is_error(err_sess) == (True, "Not logged in · Please run /login")

    ok_sess = tmp_path / "ok_session.jsonl"
    ok_sess.write_text(
        json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "Done"})
        + "\n",
        encoding="utf-8",
    )
    assert _detect_auth_failure(ok_sess, "") is None
    assert _extract_result_is_error(ok_sess) == (False, "Done")


def test_judge_ssl_context_loads_ca_certs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    ctx = _build_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.cert_store_stats().get("x509_ca", 0) > 0


def test_strip_binary_git_patches_preserves_text_diffs() -> None:
    sample = "\n".join(
        [
            "diff --git a/out/video.mp4 b/out/video.mp4",
            "new file mode 100644",
            "index 0000000..1111111",
            "GIT binary patch",
            "literal 12345",
            "zcmV(j0RR91P)h>@2!2!2",
            "",
            "diff --git a/src/MetricStory.tsx b/src/MetricStory.tsx",
            "new file mode 100644",
            "--- /dev/null",
            "+++ b/src/MetricStory.tsx",
            "@@ -0,0 +1,2 @@",
            "+export const MetricStory = () => null;",
        ]
    )
    cleaned = _strip_binary_git_patches(sample)
    assert "literal 12345" not in cleaned
    assert "zcmV(j0RR91P" not in cleaned
    assert "[binary patch payload omitted for judge]" in cleaned
    assert "diff --git a/src/MetricStory.tsx b/src/MetricStory.tsx" in cleaned
    assert "+export const MetricStory = () => null;" in cleaned


def test_trace_tracks_bash_file_edits_and_compound_verification(tmp_path: Path) -> None:
    manifest = _sample_manifest(condition="A", target_skill="test-driven-development")
    events = [
        {"type": "system", "subtype": "init", "skills": [], "tools": ["Read", "Bash"]},
        {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [
            {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "cat README.md && git ls-files"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "b1", "is_error": False, "content": "spec ok"},
        ]}},
        {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [
            {"type": "tool_use", "id": "b2", "name": "Bash", "input": {"command": "cat > tests/test_calc.py <<'EOF'\ndef test_ok():\n    assert False\nEOF\npytest -q"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "b2", "is_error": True, "content": "AssertionError: assert False"},
        ]}},
        {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [
            {"type": "tool_use", "id": "b3", "name": "Bash", "input": {"command": "cat > pricing_engine/calculator.py <<'EOF'\ndef calc():\n    return 1\nEOF\npytest -q"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "b3", "is_error": False, "content": "1 passed"},
        ]}},
        {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [
            {"type": "tool_use", "id": "b4", "name": "Bash", "input": {"command": "cat > DIAGNOSIS.md <<'EOF'\n# Notes\nEOF"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "b4", "is_error": False, "content": ""},
        ]}},
    ]
    sess = tmp_path / "bash_session.jsonl"
    sess.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    trace = analyze_trace(manifest, sess)
    assert trace.read_steps_before_first_edit == 1
    assert trace.first_edit_turn == 2
    assert trace.total_edit_calls == 3
    assert trace.unique_files_edited == 3
    assert trace.tdd_red_before_green is True
    assert trace.self_verified_after_last_edit is True


def test_jev_uncertain_items_auto_resolve_via_jev_prob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = project_root(Path(__file__).resolve().parent)
    judge_model = str(load_study_spec(root)["judge"]["model"])
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-offline")

    cache_dir = tmp_path / "jev_cache"
    cache_dir.mkdir()
    pass1 = {
        "model": judge_model,
        "answers": {
            "confident_item": {"choice": "pass", "confidence": 0.96, "probabilities": {"pass": 0.98, "fail": 0.02}},
            "low_prob_item": {"choice": "pass", "confidence": 0.56, "probabilities": {"pass": 0.78, "fail": 0.22}},
            "split_item": {"choice": "fail", "confidence": 0.14, "probabilities": {"pass": 0.43, "fail": 0.57}},
        },
    }
    pass2 = {
        "model": judge_model,
        "answers": {
            "confident_item": {"choice": "pass", "confidence": 0.92, "probabilities": {"pass": 0.96, "fail": 0.04}},
            "low_prob_item": {"choice": "pass", "confidence": 0.52, "probabilities": {"pass": 0.76, "fail": 0.24}},
            "split_item": {"choice": "pass", "confidence": 0.08, "probabilities": {"pass": 0.54, "fail": 0.46}},
        },
    }
    (cache_dir / "code1.pass1.response.json").write_text(json.dumps(pass1), encoding="utf-8")
    (cache_dir / "code1.pass2.response.json").write_text(json.dumps(pass2), encoding="utf-8")

    items = [
        {"id": "confident_item", "question": "Q1", "binary": True},
        {"id": "low_prob_item", "question": "Q2", "binary": True},
        {"id": "split_item", "question": "Q3", "binary": True},
    ]
    res = {
        r.item_id: r
        for r in evaluate_state_with_jev(
            root, "state", items, cache_dir, "code1", blind_code="code1"
        )
    }

    assert res["confident_item"].source == "jev"
    assert res["confident_item"].value == "pass"
    assert res["confident_item"].score_fraction == 1.0
    assert res["confident_item"].needs_human_review is False

    assert res["low_prob_item"].source == "jev_prob"
    assert res["low_prob_item"].value == "pass"
    assert res["low_prob_item"].score_fraction == 0.77
    assert res["low_prob_item"].needs_human_review is False

    assert res["split_item"].source == "jev_prob"
    assert res["split_item"].value == "partial"
    assert res["split_item"].score_fraction == 0.485
    assert res["split_item"].needs_human_review is False


def test_ephemeral_auth_wrapper_syncs_only_credentials() -> None:
    script = _build_ephemeral_auth_wrapper()
    assert 'EPHEMERAL_CLAUDE_DIR="/tmp/claude-ephemeral-$$"' in script
    assert 'export CLAUDE_CONFIG_DIR="${EPHEMERAL_CLAUDE_DIR}"' in script
    assert "sha256sum" in script
    assert "json.load" in script
    assert "chmod 600" in script
    assert "mv -f \"${TMP_CRED}\" /claude-auth-sync/.credentials.json" in script
    # Never sync session/state files back to the shared OAuth volume
    for forbidden_sync in ("/.claude.json", "/projects", "/sessions", "/backups"):
        assert f"/claude-auth-sync{forbidden_sync}" not in script


def test_blind_state_respects_char_budget_and_retries_token_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deliv = tmp_path / "deliverables"
    deliv.mkdir()
    for i in range(12):
        (deliv / f"module_{i}.py").write_text("x = 1\n" * 2000, encoding="utf-8")

    huge_patch = "+line = 123\n" * 10000
    state = _format_blind_state("Prompt text", huge_patch, deliv)
    assert len(state) <= MAX_BLIND_STATE_CHARS

    root = project_root(Path(__file__).resolve().parent)
    judge_model = str(load_study_spec(root)["judge"]["model"])
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-offline")

    calls: list[int] = []

    def fake_call(_endpoint: str, _api_key: str, payload: dict[str, object]) -> dict[str, object]:
        st = str(payload["state"])
        calls.append(len(st))
        if len(st) > 4000:
            raise JevTokenLimitError('{"detail":{"error_type":"max_tokens_exceeded"}}')
        return {
            "model": judge_model,
            "answers": {
                "q1": {
                    "choice": "pass",
                    "confidence": 0.95,
                    "probabilities": {"pass": 0.96, "fail": 0.04},
                }
            },
        }

    monkeypatch.setattr("skilleval.judge._call_jev_api", fake_call)
    res = evaluate_state_with_jev(
        root,
        "A" * 7000,
        [{"id": "q1", "question": "Q1", "binary": True}],
        tmp_path / "jev_cache",
        "code_retry",
        blind_code="code_retry",
    )
    assert len(calls) >= 3
    assert calls[0] > calls[-1]
    assert len(res) == 1
    assert res[0].value == "pass"


def test_review_ui_renders_turkish_visual_questions_and_captions(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "RUN-001"
    prev_dir = run_dir / "deliverables" / "_grader_previews"
    prev_dir.mkdir(parents=True)
    for fname in ("scene1_intro.png", "dataset_b_bars.png"):
        (prev_dir / fname).write_bytes(b"PNG")

    grade = GradeResult(
        run_id="RUN-001",
        task_id="G2-remotion-display",
        gates=GateResults(
            G1_CONTRACT_BUILD=True,
            G2_CRITICAL_CORRECTNESS=True,
            G3_CRITICAL_SAFETY_RULES=True,
        ),
        visual_previews=[
            "deliverables/_grader_previews/scene1_intro.png",
            "deliverables/_grader_previews/dataset_b_bars.png",
        ],
    )
    (run_dir / "grade.json").write_text(grade.model_dump_json(), encoding="utf-8")

    judge = JudgeResult(
        run_id="RUN-001",
        blind_code="abcd1234",
        judge_model="jev-1.14.0",
        visual_items=[
            JudgeItemResult(
                item_id="g2_visual_hierarchy_readability",
                dimension="visual_design",
                question="English original?",
                needs_human_review=True,
            )
        ],
        complete=False,
    )
    (run_dir / "judge.json").write_text(judge.model_dump_json(), encoding="utf-8")

    out_html = generate_blind_review_ui(tmp_path)
    html = out_html.read_text(encoding="utf-8")
    assert "Başlık, KPI kartları, çubuk grafik ve senkronize alt yazı bandı 1280×720" in html
    assert "Karttaki tüm sahne karelerini (Sahne 1–4 ve Dataset B) birlikte değerlendirin." in html
    assert "Sahne 1: Giriş (Dataset A)" in html
    assert "Dataset B: Tema & Dinamik Çubuk Kontrolü" in html
    assert "abcd1234:g2_visual_hierarchy_readability" in html
