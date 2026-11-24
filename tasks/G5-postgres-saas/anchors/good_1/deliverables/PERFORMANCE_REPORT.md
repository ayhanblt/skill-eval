# PostgreSQL SaaS Optimization Report (`EXPLAIN (ANALYZE, BUFFERS)`)

## 1. Keyset Pagination & Covering Feed (`list_active_events_page`, `list_tenant_event_feed_summary`)
- **Before (OFFSET + Sequential Scan)**:
  - Plan: `Limit -> Sort -> Seq Scan on events (cost=0.00..2390.10 rows=25 width=32) (actual time=17.420..36.810 rows=25 loops=1)`
  - Buffers: `shared hit=1248`
- **After (`(created_at, id) < (%s, %s)` + Covering Partial Composite Index `events_active_tenant_keyset_idx` with `INCLUDE (project_id, kind)`)**:
  - Plan: `Limit -> Index Only Scan using events_active_tenant_keyset_idx on events (actual time=0.032..0.068 rows=25 loops=1) | Heap Fetches: 0`
  - Buffers: `shared hit=4`

## 2. N+1 Elimination (`get_tenant_project_summaries`)
- **Before**: 21 sequential round-trips (1 project query + 20 per-project scans).
- **After**: Single `LEFT JOIN` query backed by `events_active_project_idx` (leading `project_id`), retaining zero-event projects (`Hash Aggregate`, `Buffers: shared hit=38`).

## 3. Worker Contention (`claim_next_job`)
- **Before**: `FOR UPDATE` without `SKIP LOCKED` blocked peer workers on row locks.
- **After**: Atomic `UPDATE jobs ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED)` backed by `jobs_pending_priority_idx`.

## 4. Batched Ingestion & Write-Overhead Budget (`bulk_insert_events`)
- **Before**: 500 individual `INSERT` round-trips per batch.
- **After**: Single multi-VALUES `execute_values` batch insert (1 SQL query, <12ms) and 4 targeted partial/covering indexes (`<= 6` budget).

## 5. RLS Optimization
- Preserved `ENABLE` + `FORCE ROW LEVEL SECURITY` on `projects` and `events`, wrapping `current_setting(...)` inside `(SELECT ...)` for PostgreSQL `InitPlan` caching.
