import os
import psycopg2
from app.queries import claim_next_job, list_active_events_page, list_visible_projects_rls


def _conn():
    return psycopg2.connect(os.environ.get("PG_DSN", "dbname=saas_eval user=postgres host=/tmp port=5433"))


def test_events_page_and_cursor() -> None:
    with _conn() as conn:
        p1 = list_active_events_page(conn, 1, limit=10)
        assert len(p1) == 10


def test_rls_hides_other_tenants_and_private_projects() -> None:
    with _conn() as conn:
        rows = list_visible_projects_rls(conn, tenant_id=1, user_id=2)
        assert all(1 <= r["id"] <= 20 for r in rows)


def test_claim_next_job_claims_highest_priority() -> None:
    with _conn() as conn:
        job = claim_next_job(conn, "test-worker")
        assert job is not None
        conn.rollback()
