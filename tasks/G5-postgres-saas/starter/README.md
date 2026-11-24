# Northstar SaaS PostgreSQL Optimization Task

## Schema & Data Overview
5 tables defined in `sql/migrations/001_initial_schema.sql`:
- `tenants`, `users`, `projects`, `events` (80,000 rows: ~70% archived/soft-deleted, ~30% active), `jobs` (5,000 rows: ~90% completed, ~10% pending).
- Non-superuser role `app_user` with `ENABLE` + `FORCE ROW LEVEL SECURITY` on `projects` and `events`.

## Local PostgreSQL Helper
```bash
./scripts/pg_local.sh up      # Initializes & starts PostgreSQL on port 5433 (Unix socket /tmp)
./scripts/pg_local.sh seed    # Applies migrations, loads deterministic dataset, and runs VACUUM ANALYZE
./scripts/pg_local.sh test    # Runs pytest against local DB
./scripts/pg_local.sh down    # Stops local PostgreSQL cleanly
```

## Exact Deliverables
1. `sql/migrations/002_optimizations.sql`:
   - Idempotent (`IF NOT EXISTS` / `DROP POLICY IF EXISTS`) schema indexes and optimized RLS policies.
   - Strict write-overhead budget: create **at most 6 new indexes** total across the schema while supporting active tenant feeds, project-scoped event filtering (`project_id`), pending job scheduling, and RLS lookups.
   - Keep RLS strictly enabled and enforced on `projects` and `events`.
2. `app/queries.py`:
   - Keep exact public signatures and return dict shapes for:
     - `list_active_events_page(conn, tenant_id, *, cursor_created_at=None, cursor_id=None, limit=25)`
     - `get_tenant_project_summaries(conn, tenant_id)`
     - `claim_next_job(conn, worker_id)`
     - `list_visible_projects_rls(conn, tenant_id, user_id)`
     - `list_tenant_event_feed_summary(conn, tenant_id, *, limit=50)`
     - `bulk_insert_events(conn, rows)`
3. `tests/`:
   - Add regression, concurrency, feed/bulk ingest, and RLS isolation tests verifying correctness and query efficiency.
4. `PERFORMANCE_REPORT.md`:
   - Document before vs. after `EXPLAIN (ANALYZE, BUFFERS)` query plans, buffer counts/heap fetches, concurrency behavior, and index budget choices.
