"""Hidden deterministic grader for G8-acme-release-pipeline."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from skilleval.grader_utils import run_in_sandbox
from skilleval.schemas import CheckOutcome, GateResults, GradeResult

CONTAINER_SCRIPT = r"""
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

WS = Path("/workspace")
OUT_DIR = Path("/grade_out")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def has_abs_path(obj) -> list[str]:
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            hits.extend(has_abs_path(v))
    elif isinstance(obj, list):
        for v in obj:
            hits.extend(has_abs_path(v))
    elif isinstance(obj, str):
        if obj.startswith("/") or "/workspace" in obj or "/Users/" in obj or "/home/" in obj:
            hits.append(obj)
    return hits


def validate_bundle(bundle_dir: Path, expected_head: str | None = None) -> dict:
    res = {"exists": bundle_dir.is_dir(), "errors": []}
    if not bundle_dir.is_dir():
        res["errors"].append("Bundle directory missing")
        return res

    forbidden = [
        str(p.relative_to(bundle_dir))
        for p in bundle_dir.rglob("*")
        if p.name.endswith((".tmp", ".bak", ".pyc")) or "__pycache__" in p.parts
    ]
    res["forbidden_files"] = forbidden
    if forbidden:
        res["errors"].append(f"Forbidden scratch files in bundle: {forbidden}")

    mpath = bundle_dir / "release-manifest.json"
    spath = bundle_dir / "MANIFEST.sha256"
    if not mpath.is_file():
        res["errors"].append("Missing release-manifest.json")
        return res
    if not spath.is_file():
        res["errors"].append("Missing MANIFEST.sha256")
        return res

    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except Exception as exc:
        res["errors"].append(f"Invalid manifest JSON: {exc}")
        return res

    abs_hits = has_abs_path(manifest)
    res["abs_path_hits"] = abs_hits
    if abs_hits:
        res["errors"].append(f"Absolute paths found in manifest: {abs_hits}")

    if manifest.get("bundle_format") != "acme-rel-1":
        res["errors"].append(f"Wrong bundle_format: {manifest.get('bundle_format')}")
    if str(manifest.get("version") or "").strip() != "1.4.0":
        res["errors"].append(f"Wrong version: {manifest.get('version')}")
    gc = str(manifest.get("git_commit") or "")
    if not re.match(r"^[0-9a-f]{40}$", gc):
        res["errors"].append(f"Invalid git_commit: {gc!r}")
    if expected_head and gc != expected_head:
        res["errors"].append(f"git_commit {gc} != HEAD {expected_head}")
    ts = str(manifest.get("built_at_utc") or "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", ts):
        res["errors"].append(f"built_at_utc must end with Z: {ts!r}")
    if manifest.get("rollback_verified") is not True:
        res["errors"].append(f"rollback_verified must be True: {manifest.get('rollback_verified')}")

    migs = manifest.get("migrations") or []
    if len(migs) < 3:
        res["errors"].append(f"Expected >=3 migrations (001, 002, 003), got {len(migs)}")
    for m in migs:
        if not m.get("up_sha256") or not m.get("down_sha256"):
            res["errors"].append(f"Migration missing up/down sha256: {m}")

    arts = manifest.get("artifacts") or []
    if not arts:
        res["errors"].append("artifacts list empty")
    else:
        paths = [a.get("path", "") for a in arts]
        if paths != sorted(paths):
            res["errors"].append("artifacts not sorted by path")
        for a in arts:
            rel = str(a.get("path") or "")
            ap = bundle_dir / rel
            if not ap.is_file():
                res["errors"].append(f"Artifact missing on disk: {rel}")
            else:
                if a.get("sha256") != sha256_file(ap) or int(a.get("bytes", -1)) != ap.stat().st_size:
                    res["errors"].append(f"Artifact digest/size mismatch: {rel}")

    seal_line = spath.read_text(encoding="utf-8").rstrip("\r\n")
    expected_seal = f"{sha256_file(mpath)}  release-manifest.json"
    if seal_line != expected_seal:
        res["errors"].append(f"MANIFEST.sha256 mismatch: {seal_line!r} != {expected_seal!r}")
    chk = subprocess.run(["sha256sum", "-c", "MANIFEST.sha256"], cwd=str(bundle_dir), capture_output=True, text=True, check=False)
    if chk.returncode != 0:
        res["errors"].append(f"sha256sum -c failed: {chk.stderr}")

    return res


def verify_migrations_roundtrip() -> dict:
    migs_dir = WS / "migrations"
    ups = sorted(migs_dir.glob("*.up.sql"))
    downs = sorted(migs_dir.glob("*.down.sql"))
    up_names = [p.name[:-7] for p in ups]
    down_names = [p.name[:-9] for p in downs]
    if len(ups) < 3 or up_names != down_names:
        return {"ok": False, "detail": f"Pairing mismatch ups={up_names}, downs={down_names}"}

    db_file = Path(tempfile.mkdtemp()) / "roundtrip.db"
    conn = sqlite3.connect(db_file)
    try:
        for p in ups:
            conn.executescript(p.read_text(encoding="utf-8"))
        # Smoke insert & indexed query across ledger_entries + settlement_batches
        conn.execute(
            "INSERT INTO ledger_entries (account_id, settlement_ref, amount_cents, created_at) VALUES ('a1', 's1', 500, '2026-01-01T00:00:00Z')"
        )
        rows = conn.execute("SELECT amount_cents FROM ledger_entries WHERE settlement_ref = 's1'").fetchall()
        if rows != [(500,)]:
            return {"ok": False, "detail": f"Smoke query failed on ledger_entries: {rows}"}
        conn.execute(
            "INSERT INTO settlement_batches (batch_id, status, created_at) VALUES ('b-1', 'open', '2026-01-01T00:00:00Z')"
        )
        b_rows = conn.execute("SELECT status FROM settlement_batches WHERE batch_id = 'b-1'").fetchall()
        if b_rows != [("open",)]:
            return {"ok": False, "detail": f"Smoke query failed on settlement_batches: {b_rows}"}
        # Down in reverse order
        for p in reversed(downs):
            conn.executescript(p.read_text(encoding="utf-8"))
        leftover = conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if leftover:
            return {"ok": False, "detail": f"Down migration left objects behind: {leftover}"}
        # Re-up idempotently
        for p in ups:
            conn.executescript(p.read_text(encoding="utf-8"))
        return {"ok": True, "detail": "up->smoke->down->up clean across all 3 migrations"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    finally:
        conn.close()


def main():
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd="/workspace", capture_output=True, text=True, check=True).stdout.strip()
    cand_tests = subprocess.run(
        ["/opt/skilleval-py/bin/python", "-m", "pytest", "-q"],
        cwd="/workspace",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    existing_bundle = validate_bundle(WS / "releases" / "release-1.4.0", expected_head=None)
    mig_roundtrip = verify_migrations_roundtrip()

    # Dynamic clean build
    out_clean = Path("/tmp/out_clean")
    p_clean = subprocess.run(
        ["/opt/skilleval-py/bin/python", "scripts/build_release.py", "--out", str(out_clean)],
        cwd="/workspace",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    clean_bundle = validate_bundle(out_clean, expected_head=head) if p_clean.returncode == 0 else {
        "exists": False,
        "errors": [f"build_release.py exited {p_clean.returncode}: {p_clean.stderr[-400:]}"],
    }

    # Gate Order Test A: failing test MUST abort BEFORE writing release-manifest.json
    ws_a = Path(tempfile.mkdtemp(prefix="g8-gate-a-")) / "ws"
    shutil.copytree(WS, ws_a)
    (ws_a / "tests" / "test_injected_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    out_a = Path("/tmp/out_fail_test")
    p_a = subprocess.run(
        ["/opt/skilleval-py/bin/python", "scripts/build_release.py", "--out", str(out_a)],
        cwd=str(ws_a),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    gate_a_ok = p_a.returncode != 0 and not (out_a / "release-manifest.json").exists()

    # Gate Order Test B: missing down migration MUST abort BEFORE writing release-manifest.json
    ws_b = Path(tempfile.mkdtemp(prefix="g8-gate-b-")) / "ws"
    shutil.copytree(WS, ws_b)
    down2 = ws_b / "migrations" / "002_add_settlement_index.down.sql"
    if down2.is_file():
        down2.unlink()
    out_b = Path("/tmp/out_fail_mig")
    p_b = subprocess.run(
        ["/opt/skilleval-py/bin/python", "scripts/build_release.py", "--out", str(out_b)],
        cwd=str(ws_b),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    gate_b_ok = p_b.returncode != 0 and not (out_b / "release-manifest.json").exists()

    # Gate Order Test C: broken down migration SQL MUST abort BEFORE writing release-manifest.json
    ws_c = Path(tempfile.mkdtemp(prefix="g8-gate-c-")) / "ws"
    shutil.copytree(WS, ws_c)
    (ws_c / "migrations" / "003_add_settlement_batches.down.sql").write_text(
        "DROP TABLE nonexistent_settlement_table;\n", encoding="utf-8"
    )
    out_c = Path("/tmp/out_fail_broken_down")
    p_c = subprocess.run(
        ["/opt/skilleval-py/bin/python", "scripts/build_release.py", "--out", str(out_c)],
        cwd=str(ws_c),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    gate_c_ok = p_c.returncode != 0 and not (out_c / "release-manifest.json").exists()

    test_files = list((WS / "tests").glob("test_*.py")) if (WS / "tests").is_dir() else []
    test_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in test_files)
    has_pipeline_tests = "build_release" in test_text or "rollback" in test_text.lower() or "manifest" in test_text.lower()

    payload = {
        "cand_tests_ok": cand_tests.returncode == 0,
        "cand_tests_out": cand_tests.stdout[-500:],
        "has_pipeline_tests": has_pipeline_tests,
        "existing_bundle": existing_bundle,
        "mig_roundtrip": mig_roundtrip,
        "clean_build_rc": p_clean.returncode,
        "clean_bundle": clean_bundle,
        "gate_a_abort_ok": gate_a_ok,
        "gate_b_abort_ok": gate_b_ok,
        "gate_c_abort_ok": gate_c_ok,
    }
    (OUT_DIR / "grade_payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
"""


def grade(
    run_id: str,
    workspace: Path,
    deliverables: Path,
    task_dir: Path,
) -> GradeResult:
    _ = deliverables, task_dir
    if not (workspace / "scripts" / "build_release.py").is_file() or not (
        workspace / "releases" / "release-1.4.0" / "release-manifest.json"
    ).is_file():
        return GradeResult(
            run_id=run_id,
            task_id="G8-acme-release-pipeline",
            status="missing_deliverable",
            gates=GateResults(
                G1_CONTRACT_BUILD=False,
                G2_CRITICAL_CORRECTNESS=False,
                G3_CRITICAL_SAFETY_RULES=False,
            ),
        )

    with tempfile.TemporaryDirectory(prefix="g8-grade-") as tmp:
        tdir = Path(tmp)
        s_path = tdir / "inspect_g8.py"
        s_path.write_text(CONTAINER_SCRIPT, encoding="utf-8")
        out_dir = tdir / "out"
        out_dir.mkdir()

        proc = run_in_sandbox(
            workspace,
            ["/opt/skilleval-py/bin/python", "/grade_scripts/inspect_g8.py"],
            extra_mounts={s_path: "/grade_scripts/inspect_g8.py"},
            output_dir=out_dir,
            timeout=150,
            network_none=True,
            init_git=True,
        )
        payload_file = out_dir / "grade_payload.json"
        if proc.returncode != 0 or not payload_file.is_file():
            return GradeResult(
                run_id=run_id,
                task_id="G8-acme-release-pipeline",
                status="grader_error",
                gates=GateResults(
                    G1_CONTRACT_BUILD=False,
                    G2_CRITICAL_CORRECTNESS=False,
                    G3_CRITICAL_SAFETY_RULES=False,
                ),
                error_detail=f"Sandbox inspect failed ({proc.returncode}): {proc.stderr[-600:]}",
            )
        data: dict[str, Any] = json.loads(payload_file.read_text(encoding="utf-8"))

    cand_ok = bool(data.get("cand_tests_ok"))
    ex_b = data.get("existing_bundle", {})
    cl_b = data.get("clean_bundle", {})
    mig = data.get("mig_roundtrip", {})

    existing_ok = len(ex_b.get("errors") or []) == 0
    clean_ok = data.get("clean_build_rc") == 0 and len(cl_b.get("errors") or []) == 0
    mig_ok = bool(mig.get("ok"))
    gate_abort_ok = (
        bool(data.get("gate_a_abort_ok"))
        and bool(data.get("gate_b_abort_ok"))
        and bool(data.get("gate_c_abort_ok"))
    )
    no_scratch_or_abs = (
        len(ex_b.get("forbidden_files") or []) == 0
        and len(ex_b.get("abs_path_hits") or []) == 0
        and len(cl_b.get("forbidden_files") or []) == 0
        and len(cl_b.get("abs_path_hits") or []) == 0
    )

    g1_gate = cand_ok and bool(ex_b.get("exists")) and data.get("clean_build_rc") == 0
    g2_gate = existing_ok and clean_ok and mig_ok and gate_abort_ok
    g3_gate = no_scratch_or_abs and mig_ok

    checks = [
        CheckOutcome(
            id="g8_existing_bundle_and_checksum_seal",
            dimension="correctness_completeness",
            critical=True,
            passed=existing_ok,
            detail="; ".join(ex_b.get("errors") or []) or "Existing release-1.4.0 bundle verified",
        ),
        CheckOutcome(
            id="g8_clean_rebuild_manifest_and_seal",
            dimension="correctness_completeness",
            critical=True,
            passed=clean_ok,
            detail="; ".join(cl_b.get("errors") or []) or "Clean rebuild verified",
        ),
        CheckOutcome(
            id="g8_reversible_migration_roundtrip",
            dimension="correctness_completeness",
            critical=True,
            passed=mig_ok,
            detail=str(mig.get("detail", "")),
        ),
        CheckOutcome(
            id="g8_preflight_abort_on_test_or_migration_fail",
            dimension="robustness_edge_cases",
            critical=True,
            passed=gate_abort_ok,
            detail=(
                f"test_abort={data.get('gate_a_abort_ok')}, "
                f"mig_missing_abort={data.get('gate_b_abort_ok')}, "
                f"mig_broken_abort={data.get('gate_c_abort_ok')}"
            ),
        ),
        CheckOutcome(
            id="g8_pipeline_and_service_tests",
            dimension="test_tdd_quality",
            passed=cand_ok and bool(data.get("has_pipeline_tests")),
            detail=f"cand_ok={cand_ok}, has_pipeline_tests={data.get('has_pipeline_tests')}",
        ),
        CheckOutcome(
            id="g8_no_abs_paths_no_scratch_files",
            dimension="solution_performance_security",
            critical=True,
            passed=no_scratch_or_abs,
            detail=f"forbidden={ex_b.get('forbidden_files')} {cl_b.get('forbidden_files')}, abs={ex_b.get('abs_path_hits')}",
        ),
    ]

    return GradeResult(
        run_id=run_id,
        task_id="G8-acme-release-pipeline",
        status="graded",
        gates=GateResults(
            G1_CONTRACT_BUILD=g1_gate,
            G2_CRITICAL_CORRECTNESS=g2_gate,
            G3_CRITICAL_SAFETY_RULES=g3_gate,
        ),
        checks=checks,
    )
