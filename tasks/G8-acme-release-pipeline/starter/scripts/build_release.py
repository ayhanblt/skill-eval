#!/usr/bin/env python3
"""Acme release packager & pre-flight verifier."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and seal an Acme release bundle")
    parser.add_argument("--out", default=None, help="Output bundle directory")
    _args = parser.parse_args()
    raise NotImplementedError("Implement 5-stage release pipeline according to docs/")


if __name__ == "__main__":
    raise SystemExit(main())
