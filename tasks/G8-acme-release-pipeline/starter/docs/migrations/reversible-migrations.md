# Reversible Migrations Mandate

> **Status:** Active (Canonical — Effective 2026-01-01)

1. **Mandatory Up/Down Pairing**:
   Every forward migration `migrations/NNN_name.up.sql` MUST have an exact corresponding rollback script `migrations/NNN_name.down.sql`. Missing any `.down.sql` file MUST fail the pre-flight gate immediately.

2. **Idempotent Round-Trip Verification (SQLite)**:
   Before staging any release bundle, execute the full migration chain on a fresh temporary SQLite database:
   - Step A (`up`): apply every `.up.sql` in ascending numeric order.
   - Step B (`smoke`): insert/query sample row(s) proving the schema works.
   - Step C (`down`): apply every `.down.sql` in **reverse** numeric order and assert zero user tables/indexes remain in `sqlite_master` (`type IN ('table', 'index') AND name NOT LIKE 'sqlite_%'`).
   - Step D (`re-up`): re-apply every `.up.sql` in ascending order and confirm clean re-creation without errors (`up -> smoke -> down -> up`).
