import os
from datetime import datetime, timezone
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
    dsn = os.environ.get("PG_DSN", "dbname=saas_eval user=postgres host=/tmp port=5433")
    return psycopg2.connect(dsn)


def test_events_page_and_cursor() -> None:
    with _conn() as conn:
        p1 = list_active_events_page(conn, 1, limit=10)
        assert len(p1) == 10
        p2 = list_active_events_page(
            conn,
            1,
            cursor_created_at=p1[-1]["created_at"],
            cursor_id=p1[-1]["id"],
            limit=10,
        )
        assert len(p2) == 10
        assert p1[-1]["id"] != p2[0]["id"]


def test_project_summaries_include_zero_event_projects() -> None:
    with _conn() as conn:
        rows = get_tenant_project_summaries(conn, 1)
        assert len(rows) == 20
        assert any(r["active_event_count"] == 0 for r in rows)


def test_rls_hides_other_tenants_and_private_projects() -> None:
    with _conn() as conn:
        rows = list_visible_projects_rls(conn, tenant_id=1, user_id=2)
        assert rows
        assert all(1 <= r["id"] <= 20 for r in rows)
        assert all((not r["is_private"]) or r["owner_id"] == 2 for r in rows)


def test_claim_next_job_claims_highest_priority() -> None:
    with _conn() as conn:
        job = claim_next_job(conn, "test-worker")
        assert job is not None
        assert job["status"] == "processing"
        conn.rollback()


def test_feed_summary_and_bulk_insert_smoke() -> None:
    with _conn() as conn:
        feed = list_tenant_event_feed_summary(conn, 1, limit=10)
        assert len(feed) == 10
        sample = [
            {
                "id": 999001,
                "tenant_id": 1,
                "project_id": 1,
                "status": "active",
                "kind": "audit",
                "payload": {"ok": True},
                "deleted_at": None,
                "created_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
            }
        ]
        assert bulk_insert_events(conn, sample) == 1
        conn.rollback()
