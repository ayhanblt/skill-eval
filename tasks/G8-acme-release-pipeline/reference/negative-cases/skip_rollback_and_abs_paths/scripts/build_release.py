#!/usr/bin/env python3
"""Flawed release script: skips tests/rollback checks, writes absolute paths and .tmp file."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    out = Path(args.out) if args.out else root / "releases" / "release-1.4.0"
    (out / "artifacts").mkdir(parents=True, exist_ok=True)
    (out / "scratch.tmp").write_text("temp", encoding="utf-8")
    manifest = {
        "bundle_format": "acme-rel-1",
        "version": "1.4.0",
        "git_commit": "0" * 40,
        "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "migrations": [{"name": "001_create_ledger", "up": str(root / "migrations" / "001_create_ledger.up.sql")}],
        "artifacts": [{"path": str(root / "service" / "ledger.py"), "sha256": "abc", "bytes": 10}],
        "rollback_verified": True,
    }
    mp = out / "release-manifest.json"
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "MANIFEST.sha256").write_text(f"{hashlib.sha256(mp.read_bytes()).hexdigest()}  release-manifest.json\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
