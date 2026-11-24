"""Study freeze, idempotent execution loop with quota auto-wait, grading, and tracing."""

from __future__ import annotations

import fcntl
import importlib.util
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from skilleval.capture import extract_session_telemetry, iter_jsonl, render_transcript_markdown
from skilleval.config import (
    build_matrix,
    estimate_api_equivalent_cost,
    load_rubric_spec,
    load_study_spec,
    sha256_file,
)
from skilleval.sandbox import check_claude_auth_volume, docker_image_id, run_isolated_container
from skilleval.schemas import FreezeLock, GradeResult, RunManifest, ScoreCard
from skilleval.scoring import compute_scorecard
from skilleval.trace_analyzer import analyze_trace


class QuotaExhaustedError(RuntimeError):
    """Raised when Claude subscription quota rejects an attempt."""

    def __init__(self, message: str, retry_after_seconds: int = 900) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AuthRequiredError(RuntimeError):
    """Raised when the isolated Claude OAuth volume is unsigned or expired."""


def study_dir(root: Path, study_id: str) -> Path:
    return root / "artifacts" / study_id


def collect_study_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rel_dir in ("specs", "skills", "tasks", "docker"):
        base = root / rel_dir
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if (
                not p.is_file()
                or p.name.startswith(".")
                or "__pycache__" in p.parts
                or "node_modules" in p.parts
            ):
                continue
            hashes[str(p.relative_to(root))] = sha256_file(p)
    return hashes


def freeze_study(root: Path, study_id: str, *, allow_missing_image: bool = False) -> FreezeLock:
    spec = load_study_spec(root)
    sdir = study_dir(root, study_id)
    sdir.mkdir(parents=True, exist_ok=True)
    lock_path = sdir / "freeze.lock.json"

    rows = build_matrix(root, study_id)
    image = spec["runtime"]["docker_image"]
    img_id = docker_image_id(image)
    if img_id is None and not allow_missing_image:
        raise RuntimeError(
            f"Cannot freeze study '{study_id}': Docker image '{image}' is not built."
        )

    lock = FreezeLock(
        study_id=study_id,
        created_utc=datetime.now(UTC),
        seed=int(spec["studies"][study_id]["seed"]),
        docker_image=image,
        docker_image_id=img_id,
        claude_cli_version=str(spec["runtime"]["claude_cli_version"]),
        judge_model=str(spec["judge"]["model"]),
        file_hashes=collect_study_hashes(root),
        matrix=rows,
    )

    if lock_path.is_file():
        existing = FreezeLock.model_validate_json(lock_path.read_text(encoding="utf-8"))
        if existing.file_hashes != lock.file_hashes or existing.matrix != lock.matrix:
            raise ValueError(
                f"Frozen study '{study_id}' inputs changed after freeze! "
                "Start a new study version instead of modifying frozen inputs."
            )
        return existing

    lock_path.write_text(lock.model_dump_json(indent=2) + "\n", encoding="utf-8")
    with (sdir / "matrix.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(row.model_dump_json() + "\n")
    return lock


def load_or_verify_freeze(root: Path, study_id: str) -> FreezeLock:
    lock_path = study_dir(root, study_id) / "freeze.lock.json"
    if not lock_path.is_file():
        raise FileNotFoundError(
            f"Study '{study_id}' is not frozen yet. Run `uv run skilleval freeze --study {study_id}` first."
        )
    lock = FreezeLock.model_validate_json(lock_path.read_text(encoding="utf-8"))
    current_hashes = collect_study_hashes(root)
    if current_hashes != lock.file_hashes:
        changed = sorted(
            k for k in set(current_hashes) | set(lock.file_hashes)
            if current_hashes.get(k) != lock.file_hashes.get(k)
        )
        raise ValueError(
            f"Frozen inputs drifted for '{study_id}' ({len(changed)} files changed, e.g. {changed[:5]})."
        )
    return lock


def _detect_quota_rejection(session_jsonl: Path, stderr_text: str) -> tuple[bool, int]:
    """Detect Claude subscription rate limit rejection and estimate wait duration."""
    for ev in iter_jsonl(session_jsonl):
        if (
            ev.get("type") == "rate_limit_event"
            and (ev.get("rate_limit_info") or {}).get("status") == "rejected"
        ):
            resets_at = (ev.get("rate_limit_info") or {}).get("resetsAt")
            if isinstance(resets_at, (int, float)):
                wait = max(60, int(resets_at - time.time()) + 30)
                return True, min(wait, 6 * 3600)
            return True, 900

    low = stderr_text.lower()
    if "rate limit" in low or ("limit" in low and "resets" in low):
        m = re.search(r"(\d+)\s*(minute|min|hour|hr)", low)
        if m:
            n = int(m.group(1))
            wait = n * 3600 if m.group(2).startswith("h") else n * 60
            return True, max(60, min(wait + 60, 6 * 3600))
        return True, 900
    return False, 0


def _detect_auth_failure(session_jsonl: Path, stderr_text: str) -> str | None:
    """Detect unauthenticated/expired Claude CLI session before burning a run slot."""
    for ev in iter_jsonl(session_jsonl):
        if ev.get("error") == "authentication_failed":
            return "authentication_failed"
        if ev.get("type") == "result" and ev.get("is_error") is True:
            res_str = str(ev.get("result") or "").strip()
            low_res = res_str.lower()
            if any(tok in low_res for tok in ("not logged in", "authentication", "please run /login")):
                return res_str or "authentication_failed"
    if "not logged in" in stderr_text.lower():
        return "Not logged in (stderr)"
    return None


def _extract_result_is_error(session_jsonl: Path) -> tuple[bool, str | None]:
    """Return `(is_error, result_text)` from the final `result` event in session.jsonl."""
    final_result: dict[str, Any] | None = None
    for ev in iter_jsonl(session_jsonl):
        if ev.get("type") == "result":
            final_result = ev
    if final_result is None:
        return False, None
    res_msg = str(final_result.get("result") or "").strip() or None
    return bool(final_result.get("is_error")), res_msg


def _models_match_requested(requested: str, observed: list[str]) -> bool:
    """Allow exact model ID or dated snapshot variants matching `requested`."""
    return (not observed) or all(m == requested or m.startswith(f"{requested}-") for m in observed)


def run_study(
    root: Path,
    study_id: str,
    *,
    auto_wait: bool = False,
    limit: int | None = None,
    only_task: str | None = None,
) -> dict[str, int]:
    """Idempotent execution loop across the frozen matrix with optional overnight quota wait."""
    lock = load_or_verify_freeze(root, study_id)
    logged_in, _auth_info = check_claude_auth_volume(root)
    if not logged_in:
        raise AuthRequiredError(
            "Claude OAuth volume is not signed in. Run `uv run skilleval docker-login` first."
        )
    sdir = study_dir(root, study_id)
    runs_dir = sdir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    lock_file = sdir / ".run.lock"

    completed_this_call = 0
    with lock_file.open("a") as lfh:
        try:
            fcntl.flock(lfh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another skilleval runner is already active for {study_id}.") from exc

        for row in lock.matrix:
            if only_task and row.task_id != only_task:
                continue
            slot = runs_dir / row.run_id
            manifest_path = slot / "manifest.json"
            if manifest_path.is_file():
                continue
            if limit is not None and completed_this_call >= limit:
                break

            while True:
                attempt_id = f"attempt-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
                attempt_dir = slot / "attempts" / attempt_id
                attempt_dir.mkdir(parents=True, exist_ok=True)
                started = datetime.now(UTC)
                print(
                    f"[{row.run_id}] {row.task_id} | cond={row.condition} | "
                    f"model={row.model} | rep={row.repeat}",
                    flush=True,
                )

                out = run_isolated_container(root, row, attempt_dir)
                session_jsonl = attempt_dir / "capture" / "session.jsonl"
                hook_jsonl = attempt_dir / "capture" / "hook-events.jsonl"

                rejected, wait_secs = _detect_quota_rejection(session_jsonl, out.stderr_text)
                if rejected:
                    (attempt_dir / "quota_rejected.json").write_text(
                        json.dumps({"wait_seconds": wait_secs, "stderr": out.stderr_text[:500]}, indent=2),
                        encoding="utf-8",
                    )
                    if auto_wait:
                        print(
                            f"  -> Subscription quota hit on {row.run_id}. "
                            f"Sleeping {wait_secs}s (--auto-wait) before clean retry...",
                            flush=True,
                        )
                        time.sleep(wait_secs)
                        continue
                    raise QuotaExhaustedError(
                        f"Subscription quota hit on {row.run_id}. Resume later with the exact same command.",
                        retry_after_seconds=wait_secs,
                    )

                auth_err = _detect_auth_failure(session_jsonl, out.stderr_text)
                if auth_err:
                    (attempt_dir / "auth_failed.json").write_text(
                        json.dumps({"reason": auth_err, "stderr": out.stderr_text[:500]}, indent=2),
                        encoding="utf-8",
                    )
                    raise AuthRequiredError(
                        f"Claude authentication failed on {row.run_id} ({auth_err}). "
                        "Run `uv run skilleval docker-login` and resume."
                    )

                actual_models, tokens, terminal_subtype, provider_cost = extract_session_telemetry(
                    session_jsonl
                )
                result_is_error, result_msg = _extract_result_is_error(session_jsonl)
                est_cost = provider_cost if provider_cost is not None else estimate_api_equivalent_cost(
                    root, row.model, tokens
                )

                if out.timed_out:
                    status = "timeout"
                    failure_reason = f"Container exceeded timeout ({row.timeout_seconds}s)"
                elif terminal_subtype == "error_max_turns":
                    status = "budget_exhausted"
                    failure_reason = f"Reached max_turns ({row.max_turns})"
                elif actual_models and not _models_match_requested(row.model, actual_models):
                    status = "infra_error"
                    failure_reason = f"Model mismatch: requested {row.model}, observed {actual_models}"
                elif out.exit_code == 0 and terminal_subtype == "success" and not result_is_error:
                    status = "completed"
                    failure_reason = None
                elif result_is_error:
                    status = "infra_error"
                    failure_reason = f"result_error: {(result_msg or terminal_subtype or 'unknown')[:200]}"
                else:
                    status = "infra_error" if out.exit_code != 0 else "completed"
                    failure_reason = f"exit_code={out.exit_code}, subtype={terminal_subtype}"

                capture_files = sorted(
                    str(p.relative_to(attempt_dir))
                    for p in (attempt_dir / "capture").rglob("*")
                    if p.is_file()
                )
                manifest = RunManifest(
                    run_id=row.run_id,
                    study_id=study_id,
                    attempt_id=attempt_id,
                    row=row,
                    status=status,
                    started_utc=started,
                    ended_utc=datetime.now(UTC),
                    agent_seconds=out.agent_seconds,
                    exit_code=out.exit_code,
                    terminal_subtype=terminal_subtype,
                    actual_models=actual_models,
                    effort_requested=load_study_spec(root)["studies"][study_id].get("effort", "medium"),
                    docker_image_id=out.docker_image_id,
                    claude_cli_version=lock.claude_cli_version,
                    prompt_sha256=out.prompt_sha256,
                    preload_sha256=out.preload_sha256,
                    tokens=tokens,
                    api_equivalent_cost_usd=est_cost,
                    failure_reason=failure_reason,
                    capture_files=capture_files,
                )

                # Always render human-readable full transcript inside capture/
                prompt_text = (attempt_dir / "capture" / "prompt.txt").read_text(encoding="utf-8")
                transcript_md = render_transcript_markdown(
                    manifest, prompt_text, session_jsonl, hook_jsonl if hook_jsonl.is_file() else None
                )
                (attempt_dir / "capture" / "transcript.md").write_text(
                    transcript_md, encoding="utf-8"
                )

                # Promote canonical capture/ and deliverables/ symlinks or copies to slot root
                for sub in ("capture", "deliverables", "workspace_final"):
                    target = slot / sub
                    if target.is_symlink():
                        target.unlink()
                    if not target.exists():
                        target.symlink_to((attempt_dir / sub).relative_to(slot))

                manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
                completed_this_call += 1
                break

    return study_status(root, study_id)


def _load_grader_module(root: Path, task_id: str) -> Any:
    grader_py = root / "tasks" / task_id / "grader" / "grade.py"
    if not grader_py.is_file():
        raise FileNotFoundError(f"Missing grader script for {task_id}: {grader_py}")
    spec = importlib.util.spec_from_file_location(f"grader_{task_id}", grader_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load grader module: {grader_py}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def grade_study(root: Path, study_id: str, *, force: bool = False) -> int:
    """Run independent deterministic graders for every completed/timed-out run."""
    runs_dir = study_dir(root, study_id) / "runs"
    if not runs_dir.is_dir():
        return 0
    graded_count = 0
    for slot in sorted(runs_dir.iterdir()):
        mpath = slot / "manifest.json"
        gpath = slot / "grade.json"
        if not mpath.is_file() or (gpath.is_file() and not force):
            continue
        manifest = RunManifest.model_validate_json(mpath.read_text(encoding="utf-8"))
        workspace = (slot / "workspace_final").resolve()
        started = time.monotonic()
        try:
            mod = _load_grader_module(root, manifest.row.task_id)
            result: GradeResult = mod.grade(
                run_id=manifest.run_id,
                workspace=workspace,
                deliverables=(slot / "deliverables").resolve(),
                task_dir=root / "tasks" / manifest.row.task_id,
            )
            result.grader_seconds = round(time.monotonic() - started, 3)
        except Exception as exc:  # noqa: BLE001
            result = GradeResult(
                run_id=manifest.run_id,
                task_id=manifest.row.task_id,
                status="grader_error",
                grader_seconds=round(time.monotonic() - started, 3),
                error_detail=f"{type(exc).__name__}: {exc}",
            )
        gpath.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        manifest.grader_seconds = result.grader_seconds
        mpath.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        graded_count += 1
    return graded_count


def trace_study(root: Path, study_id: str) -> int:
    """Run trace analyzer + 3-layer skill probes on every captured run."""
    runs_dir = study_dir(root, study_id) / "runs"
    if not runs_dir.is_dir():
        return 0
    count = 0
    for slot in sorted(runs_dir.iterdir()):
        mpath = slot / "manifest.json"
        if not mpath.is_file():
            continue
        manifest = RunManifest.model_validate_json(mpath.read_text(encoding="utf-8"))
        cap = (slot / "capture").resolve()
        probes = root / "skills" / manifest.row.target_skill / "probes.yaml"
        summary = analyze_trace(
            manifest,
            cap / "session.jsonl",
            patch_path=cap / "workspace.patch",
            transcript_path=cap / "transcript.md",
            deliverables_dir=(slot / "deliverables").resolve(),
            probes_path=probes if probes.is_file() else None,
        )
        (slot / "trace.json").write_text(summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
        count += 1
    return count


def score_study(root: Path, study_id: str) -> list[ScoreCard]:
    """Compute canonical ScoreCards for every run in the study."""
    from skilleval.schemas import JudgeResult, TraceSummary

    rubric = load_rubric_spec(root)
    spec = load_study_spec(root)
    visual_tasks = {t["id"] for t in spec["tasks"] if t.get("visual_review")}
    runs_dir = study_dir(root, study_id) / "runs"
    cards: list[ScoreCard] = []
    if not runs_dir.is_dir():
        return cards

    for slot in sorted(runs_dir.iterdir()):
        mpath = slot / "manifest.json"
        if not mpath.is_file():
            continue
        manifest = RunManifest.model_validate_json(mpath.read_text(encoding="utf-8"))
        grade = (
            GradeResult.model_validate_json((slot / "grade.json").read_text(encoding="utf-8"))
            if (slot / "grade.json").is_file()
            else None
        )
        trace = (
            TraceSummary.model_validate_json((slot / "trace.json").read_text(encoding="utf-8"))
            if (slot / "trace.json").is_file()
            else None
        )
        judge = (
            JudgeResult.model_validate_json((slot / "judge.json").read_text(encoding="utf-8"))
            if (slot / "judge.json").is_file()
            else None
        )
        weights = (
            rubric["product_scoring"]["visual_artifact_weights"]
            if manifest.row.task_id in visual_tasks
            else rubric["product_scoring"]["default_weights"]
        )
        card = compute_scorecard(manifest, grade, trace, judge, rubric, task_weights_override=weights)
        (slot / "scorecard.json").write_text(card.model_dump_json(indent=2) + "\n", encoding="utf-8")
        cards.append(card)
    return cards


def study_status(root: Path, study_id: str) -> dict[str, int]:
    sdir = study_dir(root, study_id)
    lock_path = sdir / "freeze.lock.json"
    planned = (
        len(FreezeLock.model_validate_json(lock_path.read_text(encoding="utf-8")).matrix)
        if lock_path.is_file()
        else len(build_matrix(root, study_id))
    )
    runs_dir = sdir / "runs"
    counts = {"planned": planned, "completed": 0, "graded": 0, "traced": 0, "judged": 0}
    if runs_dir.is_dir():
        for slot in runs_dir.iterdir():
            if (slot / "manifest.json").is_file():
                counts["completed"] += 1
            if (slot / "grade.json").is_file():
                counts["graded"] += 1
            if (slot / "trace.json").is_file():
                counts["traced"] += 1
            if (slot / "judge.json").is_file():
                counts["judged"] += 1
    return counts
