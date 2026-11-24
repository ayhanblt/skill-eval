# Acme Release Engineering Documentation

Browse internal migration policies, release packaging specifications, runbooks, deprecation notices, and operational standards below:

## Migrations
- [Migration Naming & Zero-Downtime Backfills](migrations/backfill-policy.md)
- [Lock Timeout Guards for DDL](migrations/lock-timeouts.md)
- [Reversible Migrations Mandate](migrations/reversible-migrations.md)
- [SQLite Local Parity Testing](migrations/sqlite-testing.md)

## Release Engineering & Supply Chain
- [Artifact Compression Guidelines](release/artifact-compression.md)
- [Bundle Manifest Specification](release/bundle-manifest-spec.md)
- [Canary Rollout Checkpoints](release/canary-rollout.md)
- [Checksum Sealing & Hygiene](release/checksum-sealing.md)
- [Container Tagging Policy](release/container-tagging.md)
- [SBOM Generation Notes](release/sbom-notes.md)

## Legacy & Superseded Docs
- [Forward-Only Migrations Policy (Superseded)](legacy/forward-only-migrations.md)
- [Manual Release Checklist (Superseded)](legacy/manual-release-checklist.md)
- [Legacy Bundle Manifest v0 (Superseded)](legacy/release-manifest-v1.md)

## Runbooks, Security & Operations
- [Artifact Provenance Attestation](security/artifact-provenance.md)
- [Developer Environment Bootstrapping](onboarding/dev-setup.md)
- [Emergency Hotfix Protocol](ops/hotfix-protocol.md)
- [On-Call Escalation Policy](ops/oncall-escalation.md)
- [Post-Release Smoke Verification](ops/smoke-verification.md)
- [Production Freeze Calendar](ops/freeze-calendar.md)
- [Pre-Flight Gate Order SOP](runbooks/preflight-sop.md)
- [Release Audit Retention Policy](ops/audit-retention.md)
- [Rollback Incident Drill](runbooks/rollback-drill.md)
- [Release Signer Key Custody](security/signing-key-custody.md)
