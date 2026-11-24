"""Unified CLI for skill-eval."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from skilleval.config import build_matrix, load_skill_registry, load_study_spec, project_root
from skilleval.grader_utils import verify_task_references
from skilleval.judge import calibrate_task_anchors, ensure_blind_mapping, judge_run_with_jev
from skilleval.reporting import generate_reports
from skilleval.review_ui import generate_blind_review_ui
from skilleval.runner import (
    AuthRequiredError,
    QuotaExhaustedError,
    freeze_study,
    grade_study,
    run_study,
    study_dir,
    study_status,
    trace_study,
)
from skilleval.sandbox import build_sandbox_image, login_claude_volume
from skilleval.schemas import RunManifest


def cmd_validate(args: argparse.Namespace) -> int:
    root = project_root()
    spec = load_study_spec(root)
    registry = load_skill_registry(root)
    errors: list[str] = []

    for study_id in spec.get("studies", {}):
        try:
            rows = build_matrix(root, study_id)
            by_cond = Counter(r.condition for r in rows)
            print(f"[OK] Study '{study_id}': {len(rows)} planned runs ({dict(by_cond)})")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Study '{study_id}' matrix error: {exc}")

    for sname in registry.get("skills", {}):
        sdir = root / "skills" / sname
        if not (sdir / "SKILL.md").is_file():
            errors.append(f"Missing skills/{sname}/SKILL.md")
        if not (sdir / "probes.yaml").is_file():
            errors.append(f"Missing skills/{sname}/probes.yaml")

    if args.strict_tasks:
        for task in spec["tasks"]:
            tid = task["id"]
            tdir = root / "tasks" / tid
            for req in ("task.yaml", "prompt.md", "grader/grade.py"):
                if not (tdir / req).is_file():
                    errors.append(f"Task '{tid}' missing {req}")
            if not (tdir / "starter").is_dir():
                errors.append(f"Task '{tid}' missing starter/ directory")
            if not (tdir / "reference" / "gold").is_dir():
                errors.append(f"Task '{tid}' missing reference/gold/ directory")
            neg_dir = tdir / "reference" / "negative-cases"
            negs = [p for p in neg_dir.iterdir() if p.is_dir()] if neg_dir.is_dir() else []
            if len(negs) < 2:
                errors.append(f"Task '{tid}' requires >= 2 negative cases, found {len(negs)}")
            for ndir in negs:
                if not (ndir / "expected.yaml").is_file():
                    errors.append(f"Task '{tid}' negative case '{ndir.name}' missing expected.yaml")
            anc_dir = tdir / "anchors"
            for req_anc in ("good_1", "good_2", "bad_1", "bad_2"):
                if not (anc_dir / req_anc / "expected.yaml").is_file():
                    errors.append(f"Task '{tid}' missing anchors/{req_anc}/expected.yaml")

    if errors:
        print("\nValidation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("[OK] All specs, orthogonal distractor invariants, and skill files validated.")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    root = project_root()
    rows = build_matrix(root, args.study)
    print(f"Study: {args.study} | Total runs: {len(rows)}")
    print("By condition:", dict(Counter(r.condition for r in rows)))
    print("By task:", dict(Counter(r.task_id for r in rows)))
    print("By model:", dict(Counter(r.model for r in rows)))
    if args.verbose:
        for r in rows:
            print(
                f"  {r.run_id}  {r.task_id:26s}  cond={r.condition:2s}  "
                f"model={r.model:18s}  rep={r.repeat}  installed={len(r.installed_skills)}"
            )
    return 0


def cmd_freeze(args: argparse.Namespace) -> int:
    root = project_root()
    lock = freeze_study(root, args.study, allow_missing_image=args.allow_missing_image)
    print(
        f"[FROZEN] Study '{lock.study_id}': {len(lock.matrix)} runs, "
        f"{len(lock.file_hashes)} hashed files, image={lock.docker_image_id or 'unbuilt'}"
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        st = run_study(
            root,
            args.study,
            auto_wait=args.auto_wait,
            limit=args.limit,
            only_task=args.task,
        )
        print("Status:", json.dumps(st))
        return 0
    except AuthRequiredError as exc:
        print(f"[AUTH REQUIRED] {exc}", file=sys.stderr)
        return 78
    except QuotaExhaustedError as exc:
        print(f"[QUOTA PAUSE] {exc}", file=sys.stderr)
        return 75


def cmd_grade(args: argparse.Namespace) -> int:
    root = project_root()
    n = grade_study(root, args.study, force=args.force)
    print(f"[GRADED] {n} runs in '{args.study}'.")
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    root = project_root()
    n = trace_study(root, args.study)
    print(f"[TRACED] {n} runs in '{args.study}'.")
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    root = project_root()
    sdir = study_dir(root, args.study)
    runs_dir = sdir / "runs"
    if not runs_dir.is_dir():
        print("No completed runs to judge.")
        return 0

    run_ids = sorted(p.name for p in runs_dir.iterdir() if (p / "manifest.json").is_file())
    mapping = ensure_blind_mapping(sdir, run_ids)
    human_path = sdir / "review" / "human-decisions.json"
    human_decisions = (
        json.loads(human_path.read_text(encoding="utf-8")) if human_path.is_file() else {}
    )

    pending_human = 0
    for rid in run_ids:
        manifest = RunManifest.model_validate_json(
            (runs_dir / rid / "manifest.json").read_text(encoding="utf-8")
        )
        res = judge_run_with_jev(
            root,
            sdir,
            rid,
            manifest.row.task_id,
            mapping[rid],
            dry_run=args.dry_run,
            human_decisions=human_decisions,
        )
        pending_human += sum(1 for x in (*res.items, *res.visual_items) if x.needs_human_review)

    print(f"[JUDGED] {len(run_ids)} runs | Pending blind human items: {pending_human}")
    return 0


def cmd_review_ui(args: argparse.Namespace) -> int:
    root = project_root()
    out = generate_blind_review_ui(study_dir(root, args.study))
    print(f"[REVIEW UI] Open in browser: file://{out}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    root = project_root()
    outputs = generate_reports(root, args.study)
    for k, v in outputs.items():
        print(f"  {k}: {v}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = project_root()
    print(json.dumps(study_status(root, args.study), indent=2))
    return 0


def cmd_verify_tasks(args: argparse.Namespace) -> int:
    root = project_root()
    task_ids = [args.task] if args.task else None
    all_ok, records = verify_task_references(root, task_ids)
    for rec in records:
        tag = "PASS" if rec["ok"] else "FAIL"
        print(
            f"[{tag}] {rec['task_id']:26s} | {rec['case']:28s} | "
            f"score={rec['score']} | gates={rec['gates']}"
        )
        for err in rec["errors"]:
            print(f"       -> {err}", file=sys.stderr)
    return 0 if all_ok else 1


def cmd_calibrate_anchors(args: argparse.Namespace) -> int:
    root = project_root()
    task_ids = [args.task] if args.task else None
    all_ok, records = calibrate_task_anchors(
        root, task_ids, dry_run=args.dry_run, force=args.force
    )
    for rec in records:
        tag = "OK" if rec["ok"] else "FAIL"
        probs = ", ".join(
            f"{it['id']}={it.get('min_prob', it.get('status'))}" for it in rec["items"]
        )
        print(f"[{tag}] {rec['task_id']:26s} | {rec['anchor']:8s} | {probs}")
        for err in rec["errors"]:
            print(f"       -> {err}", file=sys.stderr)
    return 0 if all_ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="skilleval", description="Agent Skills experimental harness")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="Validate specs, skill registry & distractor orthogonality")
    v.add_argument("--strict-tasks", action="store_true", help="Also require all 8 task packages")
    v.set_defaults(func=cmd_validate)

    pl = sub.add_parser("plan", help="Inspect deterministic study matrix")
    pl.add_argument("--study", default="main-v1")
    pl.add_argument("--verbose", action="store_true")
    pl.set_defaults(func=cmd_plan)

    fr = sub.add_parser("freeze", help="Hash-lock study inputs & write freeze.lock.json")
    fr.add_argument("--study", required=True)
    fr.add_argument("--allow-missing-image", action="store_true")
    fr.set_defaults(func=cmd_freeze)

    db = sub.add_parser("docker-build", help="Build deterministic sandbox Docker image")
    db.set_defaults(func=lambda _a: (print("Built:", build_sandbox_image(project_root())), 0)[1])

    dl = sub.add_parser("docker-login", help="Sign in Claude subscription OAuth volume")
    dl.set_defaults(func=lambda _a: (login_claude_volume(project_root()), 0)[1])

    rn = sub.add_parser("run", help="Run frozen matrix loop (idempotent + optional --auto-wait)")
    rn.add_argument("--study", required=True)
    rn.add_argument("--auto-wait", action="store_true", help="Sleep & resume on subscription quota")
    rn.add_argument("--limit", type=int, default=None)
    rn.add_argument("--task", type=str, default=None)
    rn.set_defaults(func=cmd_run)

    gr = sub.add_parser("grade", help="Run deterministic independent graders")
    gr.add_argument("--study", required=True)
    gr.add_argument("--force", action="store_true")
    gr.set_defaults(func=cmd_grade)

    tr = sub.add_parser("trace", help="Analyze session traces, error taxonomy & skill probes")
    tr.add_argument("--study", required=True)
    tr.set_defaults(func=cmd_trace)

    jd = sub.add_parser("judge", help="Run 2-pass atomic blind Jev evaluation & merge human review")
    jd.add_argument("--study", required=True)
    jd.add_argument("--dry-run", action="store_true")
    jd.set_defaults(func=cmd_judge)

    ru = sub.add_parser("review-ui", help="Generate offline anonymized blind review HTML gallery")
    ru.add_argument("--study", required=True)
    ru.set_defaults(func=cmd_review_ui)

    rp = sub.add_parser("report", help="Generate bilingual RAPOR.md / REPORT.md + HTML + CSV")
    rp.add_argument("--study", required=True)
    rp.set_defaults(func=cmd_report)

    st = sub.add_parser("status", help="Show progress counters for a study")
    st.add_argument("--study", default="main-v1")
    st.set_defaults(func=cmd_status)

    vt = sub.add_parser("verify-tasks", help="Verify all task graders against gold & negative references")
    vt.add_argument("--task", type=str, default=None, help="Verify a single task ID")
    vt.set_defaults(func=cmd_verify_tasks)

    ca = sub.add_parser("calibrate-anchors", help="Run 2-pass blind Jev calibration on task anchors")
    ca.add_argument("--task", type=str, default=None, help="Calibrate a single task ID")
    ca.add_argument("--dry-run", action="store_true")
    ca.add_argument("--force", action="store_true", help="Ignore cached Jev anchor responses")
    ca.set_defaults(func=cmd_calibrate_anchors)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
