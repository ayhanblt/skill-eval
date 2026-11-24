"""Optimized data-access layer for Northstar SaaS."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def list_active_events_page(
    conn: Any,
    tenant_id: int,
    *,
    cursor_created_at: datetime | None = None,
    cursor_id: int | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Return active (non-deleted, status='active') events using O(1) keyset cursor pagination."""
    with conn.cursor() as cur:
        if cursor_created_at is not None and cursor_id is not None:
            cur.execute(
                """
                SELECT id, project_id, kind, created_at
                FROM events
                WHERE tenant_id = %s
                  AND deleted_at IS NULL
                  AND status = 'active'
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (tenant_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, kind, created_at
                FROM events
                WHERE tenant_id = %s
                  AND deleted_at IS NULL
                  AND status = 'active'
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (tenant_id, limit),
            )
        rows = cur.fetchall()
    return [
        {"id": r[0], "project_id": r[1], "kind": r[2], "created_at": r[3]}
        for r in rows
    ]


def get_tenant_project_summaries(conn: Any, tenant_id: int) -> list[dict[str, Any]]:
    """Return all tenant projects + active event summaries in a single LEFT JOIN query."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              p.id,
              p.name,
              COUNT(e.id) AS active_event_count,
              MAX(e.created_at) AS last_event_at
            FROM projects p
            LEFT JOIN events e
              ON e.project_id = p.id
             AND e.deleted_at IS NULL
             AND e.status = 'active'
            WHERE p.tenant_id = %s
            GROUP BY p.id, p.name
            ORDER BY p.id ASC
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "project_id": r[0],
            "name": r[1],
            "active_event_count": int(r[2] or 0),
            "last_event_at": r[3],
        }
        for r in rows
    ]


def claim_next_job(conn: Any, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the highest-priority pending job without blocking peer workers."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'processing', worker_id = %s, locked_at = now()
            WHERE id = (
              SELECT id
              FROM jobs
              WHERE status = 'pending'
              ORDER BY priority DESC, created_at ASC, id ASC
              LIMIT 1
              FOR UPDATE SKIP LOCKED
            )
            RETURNING id, tenant_id, priority, worker_id, status
            """,
            (worker_id,),
        )
        claimed = cur.fetchone()
    if not claimed:
        return None
    return {
        "id": claimed[0],
        "tenant_id": claimed[1],
        "priority": claimed[2],
        "worker_id": claimed[3],
        "status": claimed[4],
    }


def list_visible_projects_rls(conn: Any, tenant_id: int, user_id: int) -> list[dict[str, Any]]:
    """Query projects under enforced app_user RLS with initPlan setting cache."""
    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE app_user;")
        cur.execute(
            "SELECT set_config('app.current_tenant_id', %s, true), "
            "set_config('app.current_user_id', %s, true);",
            (str(tenant_id), str(user_id)),
        )
        cur.execute(
            "SELECT id, name, owner_id, is_private FROM projects ORDER BY id ASC;"
        )
        rows = cur.fetchall()
        cur.execute("RESET ROLE;")
    return [
        {
            "id": r[0],
            "name": r[1],
            "owner_id": r[2],
            "is_private": bool(r[3]),
        }
        for r in rows
    ]
