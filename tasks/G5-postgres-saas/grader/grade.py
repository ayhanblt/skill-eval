"""Hidden deterministic grader for G5-postgres-saas."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from skilleval.grader_utils import run_in_sandbox
from skilleval.schemas import CheckOutcome, GateResults, GradeResult

CONTAINER_SCRIPT = r"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2

sys.path.insert(0, "/workspace")
OUT_DIR = Path("/grade_out")
PGDATA = Path("/tmp/pg_grade_data")
PGPORT = 5439
DSN = f"dbname=saas_eval user=postgres host=/tmp port={PGPORT}"


def _sql_text(conn, query) -> str:
    if hasattr(query, "as_string"):
        return str(query.as_string(conn))
    return str(query)


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _has_sql_offset(sql: str) -> bool:
    return bool(re.search(r"\bOFFSET\b", _strip_sql_comments(sql), re.IGNORECASE))


def _iter_plan_nodes(node: dict) -> list[dict]:
    nodes = [node]
    for child in node.get("Plans") or []:
        nodes.extend(_iter_plan_nodes(child))
    return nodes


class CountingCursor:
    def __init__(self, inner, conn, state):
        self._inner = inner
        self._conn = conn
        self._state = state

    def execute(self, query, vars=None):
        self._state["count"] += 1
        self._state["queries"].append({"sql": _sql_text(self._conn, query), "params": vars})
        return self._inner.execute(query, vars)

    def executemany(self, query, vars_list):
        rows = list(vars_list)
        self._state["count"] += len(rows)
        sql = _sql_text(self._conn, query)
        for v in rows[:5]:
            self._state["queries"].append({"sql": sql, "params": v})
        return self._inner.executemany(query, rows)

    def copy_from(self, file, table, *args, **kwargs):
        self._state["count"] += 1
        self._state["queries"].append({"sql": f"COPY {table} FROM STDIN", "params": None})
        return self._inner.copy_from(file, table, *args, **kwargs)

    def copy_expert(self, sql, file, *args, **kwargs):
        self._state["count"] += 1
        self._state["queries"].append({"sql": _sql_text(self._conn, sql), "params": None})
        return self._inner.copy_expert(sql, file, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._inner.__exit__(exc_type, exc, tb)


class CountingConn:
    def __init__(self, conn):
        self._conn = conn
        self.query_count = {"count": 0, "queries": []}

    def reset_log(self):
        self.query_count["count"] = 0
        self.query_count["queries"] = []

    def cursor(self, *args, **kwargs):
        return CountingCursor(self._conn.cursor(*args, **kwargs), self._conn, self.query_count)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def run(cmd, env=None, timeout=90):
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, check=False)


def start_postgres():
    if PGDATA.exists():
        shutil.rmtree(PGDATA)
    PGDATA.mkdir(parents=True)
    run(["initdb", "-D", str(PGDATA), "-U", "postgres", "--auth=trust"], timeout=30)
    p = run(
        ["pg_ctl", "-D", str(PGDATA), "-o", f"-k /tmp -p {PGPORT} -h ''", "-l", str(PGDATA / "pg.log"), "start"],
        timeout=30,
    )
    if p.returncode != 0:
        raise RuntimeError(f"pg_ctl start failed: {p.stderr}")
    run(["createdb", "-h", "/tmp", "-p", str(PGPORT), "-U", "postgres", "saas_eval"], timeout=15)


def stop_postgres():
    run(["pg_ctl", "-D", str(PGDATA), "stop"], timeout=15)


def explain_captured(conn, entry: dict):
    sql_body = entry["sql"].strip().rstrip(";")
    params = entry.get("params")
    with conn.cursor() as cur:
        cur.execute("SET enable_seqscan = on;")
        cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql_body, params)
        plan_root = cur.fetchone()[0][0]["Plan"]
    nodes = _iter_plan_nodes(plan_root)
    node_types = [n.get("Node Type", "") for n in nodes]
    buffers = int(plan_root.get("Shared Hit Blocks", 0)) + int(plan_root.get("Shared Read Blocks", 0))
    heap_fetches = sum(int(n.get("Heap Fetches", 0)) for n in nodes if n.get("Node Type") == "Index Only Scan")
    return node_types, buffers, heap_fetches


def main():
    report = {}
    start_postgres()
    try:
        m1 = run(["psql", "-h", "/tmp", "-p", str(PGPORT), "-U", "postgres", "-d", "saas_eval", "-v", "ON_ERROR_STOP=1", "-f", "/workspace/sql/migrations/001_initial_schema.sql"])
        if m1.returncode != 0:
            raise RuntimeError(f"001 migration failed: {m1.stderr}")

        env = dict(os.environ)
        env["PG_DSN"] = DSN
        seed_p = run(["/opt/skilleval-py/bin/python", "/workspace/scripts/seed.py"], env=env, timeout=60)
        if seed_p.returncode != 0:
            raise RuntimeError(f"seed.py failed: {seed_p.stderr}")

        with psycopg2.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public';")
                baseline_indexes = {r[0] for r in cur.fetchall()}

        m2_path = Path("/workspace/sql/migrations/002_optimizations.sql")
        m2_ok = m2_path.is_file()
        m2_err = ""
        if m2_ok and m2_path.read_text(encoding="utf-8").strip():
            m2 = run(["psql", "-h", "/tmp", "-p", str(PGPORT), "-U", "postgres", "-d", "saas_eval", "-v", "ON_ERROR_STOP=1", "-f", str(m2_path)])
            m2_ok = m2.returncode == 0
            m2_err = m2.stderr[-400:]
        run(["psql", "-h", "/tmp", "-p", str(PGPORT), "-U", "postgres", "-d", "saas_eval", "-c", "VACUUM ANALYZE;"])
        report["migration_002_ok"] = m2_ok
        report["migration_002_err"] = m2_err

        perf_doc = Path("/workspace/PERFORMANCE_REPORT.md")
        perf_text = perf_doc.read_text(encoding="utf-8", errors="replace").strip() if perf_doc.is_file() else ""
        report["perf_report_ok"] = perf_doc.is_file() and len(perf_text) >= 120

        cand_tests = subprocess.run(
            ["/opt/skilleval-py/bin/python", "-m", "pytest", "-q"],
            cwd="/workspace",
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        report["cand_tests_ok"] = cand_tests.returncode == 0
        report["cand_tests_out"] = (cand_tests.stdout + "\n" + cand_tests.stderr)[-600:]

        # Reset jobs/data cleanly after candidate tests AND vacuum visibility map before hidden checks
        run(["/opt/skilleval-py/bin/python", "/workspace/scripts/seed.py"], env=env, timeout=60)
        run(["psql", "-h", "/tmp", "-p", str(PGPORT), "-U", "postgres", "-d", "saas_eval", "-c", "VACUUM ANALYZE;"])

        from app.queries import (
            bulk_insert_events,
            claim_next_job,
            get_tenant_project_summaries,
            list_active_events_page,
            list_tenant_event_feed_summary,
            list_visible_projects_rls,
        )

        with psycopg2.connect(DSN) as conn:
            with conn.cursor() as cur:
                # 1. Index count, partial index, project_id leading index, RLS enforcement
                cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public';")
                all_idx = cur.fetchall()
                new_indexes = [(name, defn) for name, defn in all_idx if name not in baseline_indexes]
                report["new_index_count"] = len(new_indexes)
                report["has_partial_index"] = any(" WHERE " in defn.upper() for _, defn in new_indexes)
                report["has_project_id_index"] = any(
                    re.search(r"ON\s+(?:public\.)?events\s+USING\s+\w+\s*\(\s*project_id\b", defn, re.IGNORECASE)
                    for _, defn in new_indexes
                )

                cur.execute(
                    "SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('projects', 'events');"
                )
                rls_map = {r[0]: bool(r[1]) for r in cur.fetchall()}
                report["rls_enabled"] = rls_map.get("projects") is True and rls_map.get("events") is True

                cur.execute(
                    "SELECT tablename, qual FROM pg_policies WHERE schemaname = 'public' AND tablename IN ('projects', 'events');"
                )
                quals = [f"{t}:{q}" for t, q in cur.fetchall()]
                report["rls_uses_initplan"] = any(
                    "select" in q.lower() and "current_setting" in q.lower()
                    for q in quals
                )

                # Reference expected summary via SQL
                cur.execute(
                    '''
                    SELECT p.id, p.name, COUNT(e.id), MAX(e.created_at)
                    FROM projects p
                    LEFT JOIN events e
                      ON e.project_id = p.id AND e.deleted_at IS NULL AND e.status = 'active'
                    WHERE p.tenant_id = 1
                    GROUP BY p.id, p.name
                    ORDER BY p.id ASC
                    '''
                )
                expected_summaries = [
                    {"project_id": r[0], "name": r[1], "active_event_count": int(r[2]), "last_event_at": r[3]}
                    for r in cur.fetchall()
                ]

                # Reference expected deep keyset slice (skip first 400 active events for tenant 1)
                cur.execute(
                    '''
                    SELECT id, project_id, kind, created_at
                    FROM events
                    WHERE tenant_id = 1 AND deleted_at IS NULL AND status = 'active'
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1 OFFSET 399
                    '''
                )
                anchor = cur.fetchone()
                cur.execute(
                    '''
                    SELECT id, project_id, kind, created_at
                    FROM events
                    WHERE tenant_id = 1 AND deleted_at IS NULL AND status = 'active'
                      AND (created_at, id) < (%s, %s)
                    ORDER BY created_at DESC, id DESC
                    LIMIT 25
                    ''',
                    (anchor[3], anchor[0]),
                )
                expected_deep = [
                    {"id": r[0], "project_id": r[1], "kind": r[2], "created_at": r[3]}
                    for r in cur.fetchall()
                ]

                # Reference expected feed summary (top 50 active events)
                cur.execute(
                    '''
                    SELECT id, project_id, kind, created_at
                    FROM events
                    WHERE tenant_id = 1 AND deleted_at IS NULL AND status = 'active'
                    ORDER BY created_at DESC, id DESC
                    LIMIT 50
                    '''
                )
                expected_feed = [
                    {"id": r[0], "project_id": r[1], "kind": r[2], "created_at": r[3]}
                    for r in cur.fetchall()
                ]

        # 2. Pagination equivalence + executed SQL inspection (no false-positive source string grep!)
        with psycopg2.connect(DSN) as conn:
            cc_page = CountingConn(conn)
            p1 = list_active_events_page(cc_page, 1, limit=25)
            p2 = list_active_events_page(
                cc_page, 1, cursor_created_at=p1[-1]["created_at"], cursor_id=p1[-1]["id"], limit=25
            )
            cc_page.reset_log()
            p_deep = list_active_events_page(
                cc_page, 1, cursor_created_at=anchor[3], cursor_id=anchor[0], limit=25
            )
            deep_queries = list(cc_page.query_count["queries"])
            report["queries_uses_offset"] = any(_has_sql_offset(q["sql"]) for q in deep_queries)
            report["pagination_exact"] = (
                len(p1) == 25 and len(p2) == 25
                and len({r["id"] for r in p1} & {r["id"] for r in p2}) == 0
                and [r["id"] for r in p_deep] == [r["id"] for r in expected_deep]
            )
            if len(deep_queries) == 1 and deep_queries[0]["sql"].strip().upper().startswith("SELECT"):
                ntypes, bufs, _ = explain_captured(conn, deep_queries[0])
                report["events_uses_index"] = (
                    ("Index Scan" in ntypes or "Index Only Scan" in ntypes)
                    and ("Seq Scan" not in ntypes)
                )
                report["events_buffers"] = bufs
            else:
                report["events_uses_index"] = False
                report["events_buffers"] = 9999

        # 3. Feed summary covering Index Only Scan + Heap Fetches == 0 (Bottleneck 5)
        with psycopg2.connect(DSN) as conn:
            cc_feed = CountingConn(conn)
            got_feed = list_tenant_event_feed_summary(cc_feed, 1, limit=50)
            feed_queries = list(cc_feed.query_count["queries"])
            report["feed_exact"] = (got_feed == expected_feed)
            if len(feed_queries) == 1 and feed_queries[0]["sql"].strip().upper().startswith("SELECT"):
                f_types, f_bufs, f_heaps = explain_captured(conn, feed_queries[0])
                report["feed_index_only_scan"] = ("Index Only Scan" in f_types) and ("Seq Scan" not in f_types)
                report["feed_heap_fetches"] = f_heaps
                report["feed_buffers"] = f_bufs
            else:
                report["feed_index_only_scan"] = False
                report["feed_heap_fetches"] = 9999
                report["feed_buffers"] = 9999

        # 4. N+1 eliminated + zero-event project preservation
        with psycopg2.connect(DSN) as raw_conn:
            cc = CountingConn(raw_conn)
            got_sum = get_tenant_project_summaries(cc, 1)
            report["n_plus_one_query_count"] = cc.query_count["count"]
            report["summaries_exact"] = (
                got_sum == expected_summaries
                and any(x["active_event_count"] == 0 for x in got_sum)
            )

        # 5. Concurrent 2-connection SKIP LOCKED test
        c1 = psycopg2.connect(DSN)
        c2 = psycopg2.connect(DSN)
        c1.autocommit = False
        c2.autocommit = False
        try:
            j1 = claim_next_job(c1, "worker-1")
            with c2.cursor() as cur2:
                cur2.execute("SET LOCAL lock_timeout = '1200ms';")
                cur2.execute("SET LOCAL statement_timeout = '1500ms';")
            t0 = time.monotonic()
            try:
                j2 = claim_next_job(c2, "worker-2")
                dt_ms = round((time.monotonic() - t0) * 1000.0, 2)
                report["concurrent_claim_ok"] = (
                    j1 is not None and j2 is not None and j1["id"] != j2["id"] and dt_ms < 500.0
                )
                report["concurrent_claim_ms"] = dt_ms
            except Exception as exc:
                report["concurrent_claim_ok"] = False
                report["concurrent_claim_err"] = str(exc)
        finally:
            c1.rollback()
            c2.rollback()
            c1.close()
            c2.close()

        # 6. RLS isolation check across tenants & private projects
        with psycopg2.connect(DSN) as conn:
            vis_t1_u2 = list_visible_projects_rls(conn, tenant_id=1, user_id=2)
            vis_t2_u11 = list_visible_projects_rls(conn, tenant_id=2, user_id=11)
            t1_ids = {r["id"] for r in vis_t1_u2}
            t2_ids = {r["id"] for r in vis_t2_u11}
            report["rls_isolation_ok"] = (
                bool(t1_ids)
                and all(1 <= i <= 20 for i in t1_ids)
                and 1 not in t1_ids
                and bool(t2_ids)
                and all(21 <= i <= 40 for i in t2_ids)
                and not (t1_ids & t2_ids)
            )
            with conn.cursor() as cur:
                cur.execute("SET LOCAL ROLE app_user;")
                cur.execute("SELECT set_config('app.current_tenant_id', '1', true);")
                cur.execute("SELECT COUNT(*) FROM events WHERE tenant_id <> 1;")
                leak_cnt = cur.fetchone()[0]
                cur.execute("RESET ROLE;")
                report["events_rls_zero_leak"] = (leak_cnt == 0)

        # 7. Batched ingestion check: bulk_insert_events with 500 rows (Bottleneck 6)
        b_conn = psycopg2.connect(DSN)
        b_conn.autocommit = False
        try:
            base_ts = datetime(2026, 2, 1, tzinfo=timezone.utc)
            sample_rows = [
                {
                    "id": 950001 + i,
                    "tenant_id": 1,
                    "project_id": (i % 19) + 1,
                    "status": "active",
                    "kind": "audit",
                    "payload": {"batch_seq": i},
                    "deleted_at": None,
                    "created_at": base_ts + timedelta(seconds=i),
                }
                for i in range(500)
            ]
            cc_bulk = CountingConn(b_conn)
            t0 = time.monotonic()
            ret_cnt = bulk_insert_events(cc_bulk, sample_rows)
            bulk_ms = round((time.monotonic() - t0) * 1000.0, 2)
            with b_conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM events WHERE id >= 950001;")
                inserted_cnt = int(cur.fetchone()[0])
            report["bulk_ret_cnt"] = int(ret_cnt)
            report["bulk_db_cnt"] = inserted_cnt
            report["bulk_query_count"] = cc_bulk.query_count["count"]
            report["bulk_ms"] = bulk_ms
            report["bulk_insert_ok"] = (
                ret_cnt == 500
                and inserted_cnt == 500
                and cc_bulk.query_count["count"] <= 2
                and bulk_ms < 500.0
            )
        finally:
            b_conn.rollback()
            b_conn.close()

        # 8. Write budget check: batch 1,000 inserts into events
        with psycopg2.connect(DSN) as conn:
            t0 = time.monotonic()
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO events (id, tenant_id, project_id, status, kind, payload, deleted_at, created_at)
                    SELECT 900000 + g, 1, 1, 'active', 'audit', '{}'::jsonb, NULL, now()
                    FROM generate_series(1, 1000) AS g;
                    '''
                )
            insert_ms = round((time.monotonic() - t0) * 1000.0, 2)
            conn.rollback()
            report["batch_insert_ms"] = insert_ms
            report["write_perf_ok"] = insert_ms < 500.0
    finally:
        stop_postgres()

    (OUT_DIR / "grade_payload.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
"""


def grade(
    run_id: str,
    workspace: Path,
    deliverables: Path,
    task_dir: Path,
) -> GradeResult:
    _ = deliverables, task_dir
    if not (workspace / "app" / "queries.py").is_file() or not (
        workspace / "sql" / "migrations" / "002_optimizations.sql"
    ).is_file():
        return GradeResult(
            run_id=run_id,
            task_id="G5-postgres-saas",
            status="missing_deliverable",
            gates=GateResults(
                G1_CONTRACT_BUILD=False,
                G2_CRITICAL_CORRECTNESS=False,
                G3_CRITICAL_SAFETY_RULES=False,
            ),
        )

    with tempfile.TemporaryDirectory(prefix="g5-grade-") as tmp:
        tdir = Path(tmp)
        s_path = tdir / "inspect_g5.py"
        s_path.write_text(CONTAINER_SCRIPT, encoding="utf-8")
        out_dir = tdir / "out"
        out_dir.mkdir()

        proc = run_in_sandbox(
            workspace,
            ["/opt/skilleval-py/bin/python", "/grade_scripts/inspect_g5.py"],
            extra_mounts={s_path: "/grade_scripts/inspect_g5.py"},
            output_dir=out_dir,
            timeout=180,
            network_none=True,
        )
        payload_file = out_dir / "grade_payload.json"
        if proc.returncode != 0 or not payload_file.is_file():
            return GradeResult(
                run_id=run_id,
                task_id="G5-postgres-saas",
                status="grader_error",
                gates=GateResults(
                    G1_CONTRACT_BUILD=False,
                    G2_CRITICAL_CORRECTNESS=False,
                    G3_CRITICAL_SAFETY_RULES=False,
                ),
                error_detail=f"Sandbox inspect failed ({proc.returncode}): {proc.stderr[-600:]}",
            )
        data: dict[str, Any] = json.loads(payload_file.read_text(encoding="utf-8"))

    mig_ok = bool(data.get("migration_002_ok"))
    perf_ok = bool(data.get("perf_report_ok"))
    cand_ok = bool(data.get("cand_tests_ok"))

    keyset_ok = bool(data.get("pagination_exact")) and not bool(data.get("queries_uses_offset"))
    explain_ok = bool(data.get("events_uses_index")) and int(data.get("events_buffers", 9999)) < 150
    feed_ok = (
        bool(data.get("feed_exact"))
        and bool(data.get("feed_index_only_scan"))
        and int(data.get("feed_heap_fetches", 9999)) == 0
    )
    n1_ok = bool(data.get("summaries_exact")) and int(data.get("n_plus_one_query_count", 99)) <= 2
    concurrent_ok = bool(data.get("concurrent_claim_ok"))
    bulk_ok = bool(data.get("bulk_insert_ok"))
    rls_ok = bool(data.get("rls_enabled")) and bool(data.get("rls_isolation_ok")) and bool(data.get("events_rls_zero_leak"))
    idx_budget_ok = int(data.get("new_index_count", 99)) <= 6
    proj_idx_ok = bool(data.get("has_project_id_index"))
    partial_ok = bool(data.get("has_partial_index"))
    initplan_ok = bool(data.get("rls_uses_initplan"))
    write_ok = bool(data.get("write_perf_ok"))

    g1_gate = mig_ok and perf_ok and cand_ok
    g2_gate = keyset_ok and explain_ok and feed_ok and n1_ok and concurrent_ok and bulk_ok
    g3_gate = rls_ok and idx_budget_ok and proj_idx_ok and write_ok

    checks = [
        CheckOutcome(
            id="g5_migration_and_perf_report",
            dimension="correctness_completeness",
            critical=True,
            passed=mig_ok and perf_ok,
            detail=f"mig_002={mig_ok} ({data.get('migration_002_err', '')}), perf_report={perf_ok}",
        ),
        CheckOutcome(
            id="g5_keyset_pagination_and_explain",
            dimension="correctness_completeness",
            critical=True,
            passed=keyset_ok and explain_ok,
            detail=f"exact={data.get('pagination_exact')}, uses_offset={data.get('queries_uses_offset')}, index_scan={data.get('events_uses_index')}, buffers={data.get('events_buffers')}",
        ),
        CheckOutcome(
            id="g5_feed_index_only_and_bulk_insert",
            dimension="correctness_completeness",
            critical=True,
            passed=feed_ok and bulk_ok,
            detail=(
                f"feed_exact={data.get('feed_exact')}, idx_only={data.get('feed_index_only_scan')}, "
                f"heap_fetches={data.get('feed_heap_fetches')}, bulk_cnt={data.get('bulk_db_cnt')}/500, "
                f"bulk_queries={data.get('bulk_query_count')}, bulk_ms={data.get('bulk_ms')}"
            ),
        ),
        CheckOutcome(
            id="g5_n_plus_one_and_zero_event_projects",
            dimension="correctness_completeness",
            critical=True,
            passed=n1_ok,
            detail=f"exact={data.get('summaries_exact')}, queries={data.get('n_plus_one_query_count')}",
        ),
        CheckOutcome(
            id="g5_concurrent_skip_locked",
            dimension="robustness_edge_cases",
            critical=True,
            passed=concurrent_ok,
            detail=f"concurrent_ok={concurrent_ok}, ms={data.get('concurrent_claim_ms')}, err={data.get('concurrent_claim_err', '')}",
        ),
        CheckOutcome(
            id="g5_partial_index_and_rls_initplan",
            dimension="robustness_edge_cases",
            passed=partial_ok and initplan_ok,
            detail=f"partial_index={partial_ok}, initplan={initplan_ok}",
        ),
        CheckOutcome(
            id="g5_candidate_pytest_passes",
            dimension="test_tdd_quality",
            critical=True,
            passed=cand_ok,
            detail=data.get("cand_tests_out", ""),
        ),
        CheckOutcome(
            id="g5_rls_enforced_and_index_budget",
            dimension="solution_performance_security",
            critical=True,
            passed=rls_ok and idx_budget_ok and proj_idx_ok and write_ok,
            detail=f"rls_ok={rls_ok}, new_indexes={data.get('new_index_count')}/6, proj_idx={proj_idx_ok}, batch_insert_ms={data.get('batch_insert_ms')}",
        ),
    ]

    return GradeResult(
        run_id=run_id,
        task_id="G5-postgres-saas",
        status="graded",
        gates=GateResults(
            G1_CONTRACT_BUILD=g1_gate,
            G2_CRITICAL_CORRECTNESS=g2_gate,
            G3_CRITICAL_SAFETY_RULES=g3_gate,
        ),
        checks=checks,
        solution_performance={
            "events_buffers": data.get("events_buffers"),
            "feed_heap_fetches": data.get("feed_heap_fetches"),
            "n_plus_one_queries": data.get("n_plus_one_query_count"),
            "bulk_insert_queries": data.get("bulk_query_count"),
            "concurrent_claim_ms": data.get("concurrent_claim_ms"),
            "new_index_count": data.get("new_index_count"),
            "batch_insert_ms": data.get("batch_insert_ms"),
        },
    )
