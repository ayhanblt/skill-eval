#!/usr/bin/env python3
"""Flawed release script: emits manifest even on test failure, wrong bundle_format, no MANIFEST.sha256."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    out = Path(args.out) if args.out else root / "releases" / "release-1.4.0"
    out.mkdir(parents=True, exist_ok=True)
    (out / "release-manifest.json").write_text(
        json.dumps({"bundle_format": "v1", "version": "1.4.0", "rollback_verified": False}, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
