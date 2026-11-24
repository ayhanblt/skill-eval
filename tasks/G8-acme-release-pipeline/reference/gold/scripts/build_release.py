#!/usr/bin/env python3
"""Acme 5-stage release packager & pre-flight verifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_migrations_roundtrip(root: Path) -> list[dict[str, str]]:
    mig_dir = root / "migrations"
    ups = sorted(mig_dir.glob("*.up.sql"))
    if not ups:
        raise RuntimeError("No .up.sql migrations found")

    entries: list[dict[str, str]] = []
    downs_in_order: list[Path] = []
    for up_path in ups:
        stem = up_path.name[: -len(".up.sql")]
        down_path = mig_dir / f"{stem}.down.sql"
        if not down_path.is_file():
            raise RuntimeError(f"Missing matching down migration: {down_path.name}")
        downs_in_order.append(down_path)
        entries.append(
            {
                "name": stem,
                "up": f"migrations/{up_path.name}",
                "down": f"migrations/{down_path.name}",
                "up_sha256": _sha256_file(up_path),
                "down_sha256": _sha256_file(down_path),
            }
        )

    with tempfile.TemporaryDirectory(prefix="acme-mig-") as tmp:
        conn = sqlite3.connect(Path(tmp) / "preflight.db")
        try:
            for p in ups:
                conn.executescript(p.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO ledger_entries (account_id, settlement_ref, amount_cents, created_at) "
                "VALUES ('acct-1', 'settle-1', 1000, '2026-01-01T00:00:00Z')"
            )
            found = conn.execute(
                "SELECT amount_cents FROM ledger_entries WHERE settlement_ref = 'settle-1'"
            ).fetchall()
            if found != [(1000,)]:
                raise RuntimeError(f"Migration smoke query failed: {found}")
            conn.execute(
                "INSERT INTO settlement_batches (batch_id, status, created_at) "
                "VALUES ('batch-1', 'open', '2026-01-01T00:00:00Z')"
            )
            batch_rows = conn.execute(
                "SELECT status FROM settlement_batches WHERE batch_id = 'batch-1'"
            ).fetchall()
            if batch_rows != [("open",)]:
                raise RuntimeError(f"Batch smoke query failed: {batch_rows}")

            for p in reversed(downs_in_order):
                conn.executescript(p.read_text(encoding="utf-8"))
            leftover = conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if leftover:
                raise RuntimeError(f"Rollback left objects behind: {leftover}")

            for p in ups:
                conn.executescript(p.read_text(encoding="utf-8"))
        finally:
            conn.close()
    return entries


def _run_tests(root: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Pre-flight pytest failed:\n{proc.stdout}\n{proc.stderr}")


def _stage_artifacts(root: Path, bundle_dir: Path) -> list[dict[str, object]]:
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    art_root = bundle_dir / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(root / "VERSION", art_root / "VERSION")
    shutil.copytree(
        root / "service",
        art_root / "service",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.tmp", "*.bak"),
    )
    shutil.copytree(
        root / "migrations",
        art_root / "migrations",
        ignore=shutil.ignore_patterns("__pycache__", "*.tmp", "*.bak"),
    )

    records: list[dict[str, object]] = []
    for p in sorted(art_root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(bundle_dir).as_posix()
        records.append(
            {
                "path": rel,
                "sha256": _sha256_file(p),
                "bytes": p.stat().st_size,
            }
        )
    records.sort(key=lambda item: str(item["path"]))
    for p in bundle_dir.rglob("*"):
        if p.name.endswith((".tmp", ".bak", ".pyc")) or "__pycache__" in p.parts:
            raise RuntimeError(f"Scratch artifact forbidden in bundle: {p}")
    return records


def build_release(root: Path, out_dir: Path | None = None) -> Path:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    bundle_dir = out_dir or (root / "releases" / f"release-{version}")

    # Stage 1: Migration pairing + SQLite up -> smoke -> down -> up round-trip
    migrations = _verify_migrations_roundtrip(root)
    # Stage 2: Full test suite
    _run_tests(root)

    git_env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        env=git_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Stage 3: Clean deterministic artifact staging
    artifacts = _stage_artifacts(root, bundle_dir)

    # Stage 4: Release manifest + MANIFEST.sha256 seal
    manifest = {
        "bundle_format": "acme-rel-1",
        "version": version,
        "git_commit": git_commit,
        "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "migrations": migrations,
        "artifacts": artifacts,
        "rollback_verified": True,
    }
    manifest_path = bundle_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    seal_path = bundle_dir / "MANIFEST.sha256"
    seal_path.write_text(f"{_sha256_file(manifest_path)}  release-manifest.json\n", encoding="utf-8")

    # Stage 5: Final checksum verification
    chk = subprocess.run(
        ["sha256sum", "-c", "MANIFEST.sha256"],
        cwd=str(bundle_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if chk.returncode != 0:
        raise RuntimeError(f"Checksum verification failed: {chk.stderr}")
    return bundle_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and seal an Acme release bundle")
    parser.add_argument("--out", default=None, help="Output bundle directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    out_dir = Path(args.out) if args.out else None
    bundle = build_release(root, out_dir)
    print(f"Built verified release bundle: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
