import os
from datetime import datetime, timedelta, timezone
import psycopg2
from app.queries import (
    bulk_insert_events,
    claim_next_job,
    get_tenant_project_summaries,
    list_active_events_page,
    list_tenant_event_feed_summary,
    list_visible_projects_rls,
)


def _conn():
    return psycopg2.connect(os.environ.get("PG_DSN", "dbname=saas_eval user=postgres host=/tmp port=5433"))


def test_concurrent_workers_do_not_block() -> None:
    c1 = _conn()
    c2 = _conn()
    try:
        j1 = claim_next_job(c1, "w1")
        with c2.cursor() as cur2:
            cur2.execute("SET LOCAL lock_timeout = '500ms';")
        j2 = claim_next_job(c2, "w2")
        assert j1 is not None and j2 is not None and j1["id"] != j2["id"]
    finally:
        c1.rollback()
        c2.rollback()
        c1.close()
        c2.close()


def test_keyset_page_summaries_and_feed_covering_index() -> None:
    with _conn() as conn:
        p1 = list_active_events_page(conn, 1, limit=25)
        p2 = list_active_events_page(conn, 1, cursor_created_at=p1[-1]["created_at"], cursor_id=p1[-1]["id"], limit=25)
        assert not ({x["id"] for x in p1} & {x["id"] for x in p2})
        assert len(get_tenant_project_summaries(conn, 1)) == 20
        feed = list_tenant_event_feed_summary(conn, 1, limit=50)
        assert len(feed) == 50
        assert feed[:25] == p1
        rls_rows = list_visible_projects_rls(conn, tenant_id=1, user_id=2)
        assert rls_rows and 1 not in {r["id"] for r in rls_rows}


def test_bulk_insert_events_batched() -> None:
    with _conn() as conn:
        base_ts = datetime(2026, 2, 1, tzinfo=timezone.utc)
        rows = [
            {
                "id": 980000 + i,
                "tenant_id": 1,
                "project_id": (i % 19) + 1,
                "status": "active",
                "kind": "audit",
                "payload": {"i": i},
                "deleted_at": None,
                "created_at": base_ts + timedelta(seconds=i),
            }
            for i in range(100)
        ]
        assert bulk_insert_events(conn, rows) == 100
        conn.rollback()
