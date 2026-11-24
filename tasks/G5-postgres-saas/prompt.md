Optimize a 5-table multi-tenant SaaS PostgreSQL database and data-access layer (`sql/migrations/002_optimizations.sql` and `app/queries.py`) that currently suffer from six production bottlenecks.

Requirements summary:
1. Read `README.md`, `sql/migrations/001_initial_schema.sql`, `app/queries.py`, `scripts/seed.py`, and `tests/test_correctness.py` carefully. You can spin up the local PostgreSQL instance with `./scripts/pg_local.sh up && ./scripts/pg_local.sh seed`.
2. Diagnose and resolve all six production bottlenecks while strictly preserving behavior, Row-Level Security (RLS) tenant/private-project isolation, and write throughput (`<= 6` new indexes total in `002_optimizations.sql`):
   - Deep pagination over active events (`list_active_events_page`) suffers high latency and buffer reads on `events` (`~70%` archived/soft-deleted).
   - Tenant project dashboard aggregation (`get_tenant_project_summaries`) executes an N+1 query storm and must preserve projects with `0` active events.
   - Concurrent background workers calling `claim_next_job` block each other under lock contention on `jobs`.
   - RLS policy checks in `list_visible_projects_rls` and table policies incur excessive per-row setting evaluation overhead (keep RLS enabled and enforced).
   - Lightweight recent-feed reads in `list_tenant_event_feed_summary` cause unnecessary table heap page fetches under heavy read load.
   - Event ingestion in `bulk_insert_events` executes per-row round-trips instead of batched ingestion, while project-scoped event queries lack leading `project_id` index support.
3. Preserve the exact function names, arguments, and return schemas in `app/queries.py`.
4. Add or expand automated tests under `tests/`, verify everything with `./scripts/pg_local.sh test` (or `pytest`), and capture concrete before/after `EXPLAIN (ANALYZE, BUFFERS)` metrics and index trade-offs in `PERFORMANCE_REPORT.md`.
