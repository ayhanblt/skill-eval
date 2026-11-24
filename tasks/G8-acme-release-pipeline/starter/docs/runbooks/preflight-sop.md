# Pre-Flight Gate Order SOP (`scripts/build_release.py`)

> **Status:** Active (Canonical — Effective 2026-01-01)

`scripts/build_release.py --out <bundle_dir>` (defaulting to `releases/release-<VERSION>`) MUST execute these 5 stages in exact order:

1. **Stage 1 — Migration Pairing & Rollback Round-Trip**: Verify every `NNN_*.up.sql` has a matching `NNN_*.down.sql` and passes ephemeral SQLite `up -> smoke -> down -> up`.
2. **Stage 2 — Unit & Contract Tests**: Run `pytest -q` across the repository test suite.
3. **Stage 3 — Deterministic Artifact Staging**: Only AFTER Stage 1 and Stage 2 pass, stage clean copies of `VERSION`, `service/` (excluding `__pycache__`/`.pyc`), and `migrations/` into `<bundle_dir>/artifacts/`.
4. **Stage 4 — Manifest & Checksum Seal**: Write `<bundle_dir>/release-manifest.json` (`bundle_format: "acme-rel-1"`, `rollback_verified: true`) and `<bundle_dir>/MANIFEST.sha256`.
5. **Stage 5 — Final Checksum Verification**: Verify `MANIFEST.sha256` against `release-manifest.json` (`sha256sum -c`).

**Critical Abort Rule**: If Stage 1 or Stage 2 fails, `build_release.py` MUST exit non-zero immediately and MUST NEVER write or leave behind `<bundle_dir>/release-manifest.json` or `MANIFEST.sha256`.
