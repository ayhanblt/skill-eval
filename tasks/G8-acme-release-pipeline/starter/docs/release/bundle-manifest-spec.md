# Release Bundle Manifest Specification (`acme-rel-1`)

> **Status:** Active (Canonical — Effective 2026-01-01)

Target bundle path for version `1.4.0` (read from `VERSION`): `releases/release-1.4.0/`.

`<bundle_dir>/release-manifest.json` MUST be a JSON object with these exact keys:

- `bundle_format`: `"acme-rel-1"`
- `version`: SemVer string read from `VERSION` (trimmed, e.g., `"1.4.0"`)
- `git_commit`: 40-character lowercase hex SHA from `git rev-parse HEAD`
- `built_at_utc`: RFC 3339 UTC timestamp ending strictly with `"Z"`
- `migrations`: ordered list of migration entries (`001_...`, `002_...`):
  ```json
  {
    "name": "001_create_ledger",
    "up": "migrations/001_create_ledger.up.sql",
    "down": "migrations/001_create_ledger.down.sql",
    "up_sha256": "<64-hex>",
    "down_sha256": "<64-hex>"
  }
  ```
- `artifacts`: list sorted lexicographically by `path` covering every non-manifest file staged inside `<bundle_dir>/artifacts/` (e.g., `service/ledger.py`, `migrations/*.sql`, `VERSION`):
  ```json
  {
    "path": "artifacts/service/ledger.py",
    "sha256": "<64-hex>",
    "bytes": 412
  }
  ```
- `rollback_verified`: boolean `true` (ONLY after completing the ephemeral rollback round-trip check).

## Strict Path Hygiene
NEVER write absolute paths (starting with `/` or containing `/workspace` or host directories) anywhere inside `release-manifest.json`. Every `up`, `down`, and `path` value MUST be relative to `<bundle_dir>` / repo root.
