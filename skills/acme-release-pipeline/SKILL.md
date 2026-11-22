---
name: acme-release-pipeline
description: Use when preparing, verifying, signing, or rolling back an Acme internal release bundle, database migration pack, or deployment manifest.
---

# Acme Release Pipeline SOP

Follow this exact sequence whenever assembling or validating an Acme release bundle (detailed rationale is also documented across `docs/release/`, `docs/migrations/`, and `docs/runbooks/`):

1. **Strict Pre-Flight Gate Order**
   - Execute checks in order: (1) schema/migration dry-run, (2) unit & contract tests, (3) deterministic artifact bundle build, (4) SHA-256 manifest generation, (5) rollback plan verification. Never generate a release manifest before tests pass.
2. **Deterministic Release Manifest (`release-manifest.json`)**
   - Must contain `bundle_format: "acme-rel-1"`, `version` (SemVer), `git_commit`, `built_at_utc` (`Z`), `migrations` (ordered list with `up_sha256` and `down_sha256`), `artifacts` (sorted relative paths with `sha256` and `bytes`), and `rollback_verified: true`.
3. **Reversible Migration Mandate**
   - Every forward migration `NNN_name.up.sql` MUST have a matching `NNN_name.down.sql`.
   - Verify rollback on an ephemeral database by running `up` → smoke assertion → `down` → `up` again (idempotent round-trip).
4. **Checksum Seal (`MANIFEST.sha256`)**
   - Write standard two-space `<sha256>  release-manifest.json` file alongside the bundle and verify it with `sha256sum -c` (or equivalent Python check) as the final step.
5. **Forbidden Shortcuts**
   - Never leave temporary `.tmp` / `.bak` files inside the bundle directory; never skip the `down` migration check; never emit absolute host paths inside `release-manifest.json`.
