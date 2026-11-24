"""Shared sandbox execution, reference materialization, and task verification utilities."""

from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from skilleval.config import load_rubric_spec, load_study_spec
from skilleval.judge import load_task_judge_items
from skilleval.schemas import (
    GradeResult,
    JudgeItemResult,
    JudgeResult,
    MatrixRow,
    RunManifest,
)
from skilleval.scoring import compute_scorecard


def _chmod_tree_rw(path: Path) -> None:
    if not path.exists():
        return
    for item in [path, *path.rglob("*")]:
        try:
            mode = item.stat().st_mode
            if item.is_dir():
                os.chmod(item, mode | 0o777)
            elif not item.is_symlink():
                os.chmod(item, mode | 0o666)
        except OSError:
            pass


def run_in_sandbox(
    workspace: Path,
    command: list[str] | str,
    *,
    image: str | None = None,
    extra_mounts: dict[Path, str] | None = None,
    output_dir: Path | None = None,
    timeout: int = 180,
    network_none: bool = True,
    link_node_modules: bool = False,
    init_git: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a grading command inside a clean disposable container copy of `workspace`."""
    resolved_image = image or os.environ.get("SKILLEVAL_DOCKER_IMAGE") or "skilleval-sandbox:latest"
    cmd_str = command if isinstance(command, str) else shlex.join(command)

    with tempfile.TemporaryDirectory(prefix="skilleval-grade-") as tmp:
        stage = Path(tmp)
        tmp_ws = stage / "workspace"
        shutil.copytree(
            workspace,
            tmp_ws,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".claude"),
        )
        if init_git:
            git_env = {
                **os.environ,
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "skilleval",
                "GIT_AUTHOR_EMAIL": "skilleval@local",
                "GIT_COMMITTER_NAME": "skilleval",
                "GIT_COMMITTER_EMAIL": "skilleval@local",
            }
            subprocess.run(["git", "init", "-q"], cwd=tmp_ws, env=git_env, check=True)
            subprocess.run(["git", "add", "-A"], cwd=tmp_ws, env=git_env, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "grade-snapshot"],
                cwd=tmp_ws,
                env=git_env,
                check=True,
            )

        _chmod_tree_rw(tmp_ws)
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            _chmod_tree_rw(output_dir)

        prologue = [
            "export HOME=/tmp/grader-home",
            "export GIT_CONFIG_GLOBAL=/dev/null",
            "export GIT_CONFIG_NOSYSTEM=1",
            "mkdir -p \"$HOME\"",
        ]
        if link_node_modules:
            prologue.append(
                "if [ -d /opt/skilleval-node/node_modules ] && [ ! -e /workspace/node_modules ]; "
                "then ln -s /opt/skilleval-node/node_modules /workspace/node_modules; fi"
            )
        full_shell = " && ".join(prologue) + f" && {cmd_str}"

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-w",
            "/workspace",
            "-v",
            f"{tmp_ws}:/workspace:rw",
        ]
        if network_none:
            docker_cmd.extend(["--network", "none"])
        if output_dir is not None:
            docker_cmd.extend(["-v", f"{output_dir.resolve()}:/grade_out:rw"])
        for host_path, container_path in (extra_mounts or {}).items():
            docker_cmd.extend(["-v", f"{host_path.resolve()}:{container_path}:ro"])
        docker_cmd.extend([resolved_image, "bash", "-lc", full_shell])

        return subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )


def materialize_reference(
    starter_dir: Path,
    overlay_dir: Path,
    ws_dir: Path,
    deliv_dir: Path | None = None,
) -> dict[str, Any]:
    """Copy `starter_dir` and overlay `overlay_dir` files (excluding `expected.yaml`)."""
    if ws_dir.exists():
        shutil.rmtree(ws_dir)
    shutil.copytree(
        starter_dir,
        ws_dir,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".DS_Store"),
    )

    expected_path = overlay_dir / "expected.yaml"
    expected: dict[str, Any] = {}
    if expected_path.is_file():
        expected = yaml.safe_load(expected_path.read_text(encoding="utf-8")) or {}

    for src in sorted(overlay_dir.rglob("*")):
        if not src.is_file() or src.name in ("expected.yaml", ".DS_Store"):
            continue
        if "__pycache__" in src.parts or "node_modules" in src.parts:
            continue
        rel = src.relative_to(overlay_dir)
        dst_ws = ws_dir / rel
        dst_ws.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst_ws)
        if deliv_dir is not None:
            dst_deliv = deliv_dir / rel
            dst_deliv.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst_deliv)

    for rel_del in expected.get("delete_files") or []:
        target = ws_dir / rel_del
        if target.is_file():
            target.unlink()
        if deliv_dir is not None:
            dtarget = deliv_dir / rel_del
            if dtarget.is_file():
                dtarget.unlink()

    return expected


def _simulated_perfect_judge(root: Path, task_id: str) -> JudgeResult:
    jev_items, visual_items = load_task_judge_items(root, task_id)
    return JudgeResult(
        run_id="REF-001",
        blind_code="ref00001",
        judge_model="simulated-ref",
        items=[
            JudgeItemResult(
                item_id=str(it["id"]),
                dimension=it.get("dimension", "code_output_maintainability"),
                question=str(it["question"]),
                value="pass",
                score_fraction=1.0,
                source="jev",
            )
            for it in jev_items
        ],
        visual_items=[
            JudgeItemResult(
                item_id=str(it["id"]),
                dimension="visual_design",
                question=str(it["question"]),
                value="pass",
                score_fraction=1.0,
                source="human_blind",
            )
            for it in visual_items
        ],
        complete=True,
    )


def _load_grader(root: Path, task_id: str) -> Any:
    grader_py = root / "tasks" / task_id / "grader" / "grade.py"
    spec = importlib.util.spec_from_file_location(f"verify_grader_{task_id}", grader_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load grader: {grader_py}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verify_task_references(
    root: Path, task_ids: list[str] | None = None
) -> tuple[bool, list[dict[str, Any]]]:
    """Verify gold (>=9.5 & all gates pass) and negative cases (expected failures) per task."""
    spec = load_study_spec(root)
    rubric = load_rubric_spec(root)
    wanted = set(task_ids) if task_ids else None
    all_ok = True
    records: list[dict[str, Any]] = []

    for task in spec["tasks"]:
        tid = task["id"]
        if wanted and tid not in wanted:
            continue
        tdir = root / "tasks" / tid
        starter_dir = tdir / "starter"
        mod = _load_grader(root, tid)
        weights = (
            rubric["product_scoring"]["visual_artifact_weights"]
            if task.get("visual_review")
            else rubric["product_scoring"]["default_weights"]
        )
        manifest = RunManifest(
            run_id=f"REF-{tid}",
            study_id="reference-check",
            attempt_id="attempt-ref",
            row=MatrixRow(
                run_id=f"REF-{tid}",
                study_id="reference-check",
                phase="calibration",
                task_id=tid,
                archetype=task["archetype"],
                target_skill=task["target_skill"],
                condition="A",
                model="claude-sonnet-5-5",
                repeat=1,
            ),
            status="completed",
            started_utc=datetime.now(UTC),
        )
        perfect_judge = _simulated_perfect_judge(root, tid)

        # 1. Gold reference check
        gold_dir = tdir / "reference" / "gold"
        with tempfile.TemporaryDirectory(prefix=f"ref-gold-{tid}-") as tmp:
            tpath = Path(tmp)
            ws = tpath / "workspace"
            deliv = tpath / "deliverables"
            deliv.mkdir()
            materialize_reference(starter_dir, gold_dir, ws, deliv)
            grade: GradeResult = mod.grade(
                run_id=f"GOLD-{tid}",
                workspace=ws,
                deliverables=deliv,
                task_dir=tdir,
            )
            card = compute_scorecard(
                manifest, grade, None, perfect_judge, rubric, task_weights_override=weights
            )
            errors: list[str] = []
            if grade.status != "graded":
                errors.append(f"status={grade.status}: {grade.error_detail}")
            if not grade.gates.all_passed:
                errors.append(f"gates={grade.gates.model_dump()}")
            if card.passed is not True:
                errors.append(f"card.passed={card.passed}")
            if card.product_score is None or card.product_score < 9.5:
                errors.append(f"product_score={card.product_score} < 9.5")
            ok = not errors
            if not ok:
                all_ok = False
            failed_checks = [c.id for c in grade.checks if c.passed is False]
            records.append(
                {
                    "task_id": tid,
                    "case": "gold",
                    "ok": ok,
                    "score": card.product_score,
                    "gates": grade.gates.model_dump(),
                    "failed_checks": failed_checks,
                    "errors": errors,
                }
            )

        # 2. Negative cases check
        neg_root = tdir / "reference" / "negative-cases"
        neg_dirs = sorted(p for p in neg_root.iterdir() if p.is_dir()) if neg_root.is_dir() else []
        if len(neg_dirs) < 2:
            all_ok = False
            records.append(
                {
                    "task_id": tid,
                    "case": "negative-cases",
                    "ok": False,
                    "score": None,
                    "gates": {},
                    "failed_checks": [],
                    "errors": [f"Expected >= 2 negative cases, found {len(neg_dirs)}"],
                }
            )
        for ndir in neg_dirs:
            with tempfile.TemporaryDirectory(prefix=f"ref-neg-{tid}-{ndir.name}-") as tmp:
                tpath = Path(tmp)
                ws = tpath / "workspace"
                deliv = tpath / "deliverables"
                deliv.mkdir()
                expected = materialize_reference(starter_dir, ndir, ws, deliv)
                grade = mod.grade(
                    run_id=f"NEG-{tid}-{ndir.name}",
                    workspace=ws,
                    deliverables=deliv,
                    task_dir=tdir,
                )
                card = compute_scorecard(
                    manifest, grade, None, perfect_judge, rubric, task_weights_override=weights
                )
                errors = []
                must_fail_gates = expected.get("must_fail_gates") or []
                for gname in must_fail_gates:
                    if getattr(grade.gates, gname, None) is not False:
                        errors.append(f"Expected gate {gname}=False, got {getattr(grade.gates, gname, None)}")
                check_map = {c.id: c for c in grade.checks}
                for cid in expected.get("must_fail_checks") or []:
                    chk = check_map.get(cid)
                    if chk is None:
                        errors.append(f"Expected check '{cid}' missing from GradeResult")
                    elif chk.passed is not False and (chk.score_fraction is None or chk.score_fraction >= 0.5):
                        errors.append(f"Expected check '{cid}' to fail, got passed={chk.passed} frac={chk.score_fraction}")
                max_score = expected.get("max_product_score")
                if max_score is not None and (card.product_score is None or card.product_score > float(max_score)):
                    errors.append(f"Expected product_score <= {max_score}, got {card.product_score}")
                if card.passed is not False:
                    errors.append(f"Expected negative case to FAIL, got card.passed={card.passed}")
                ok = not errors
                if not ok:
                    all_ok = False
                records.append(
                    {
                        "task_id": tid,
                        "case": f"neg:{ndir.name}",
                        "ok": ok,
                        "score": card.product_score,
                        "gates": grade.gates.model_dump(),
                        "failed_checks": [c.id for c in grade.checks if c.passed is False],
                        "errors": errors,
                    }
                )

    return all_ok, records
