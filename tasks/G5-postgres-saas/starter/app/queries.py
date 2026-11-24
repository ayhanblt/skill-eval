"""Data-access layer for Northstar SaaS (baseline with intentional bottlenecks)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def list_active_events_page(
    conn: Any,
    tenant_id: int,
    *,
    cursor_created_at: datetime | None = None,
    cursor_id: int | None = None,
    limit: int = 25,
    page: int = 1,
) -> list[dict[str, Any]]:
    """Return active (non-deleted, status='active') events ordered newest first."""
    offset = max(0, (page - 1) * limit)
    with conn.cursor() as cur:
        if cursor_created_at is not None and cursor_id is not None:
            # Baseline bottleneck: expensive row filtering without cursor index support
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
                LIMIT %s OFFSET %s
                """,
                (tenant_id, limit, offset),
            )
        rows = cur.fetchall()
    return [
        {"id": r[0], "project_id": r[1], "kind": r[2], "created_at": r[3]}
        for r in rows
    ]


def get_tenant_project_summaries(conn: Any, tenant_id: int) -> list[dict[str, Any]]:
    """Return all projects for tenant_id with active event count and last_event_at."""
    # Baseline bottleneck: repeated per-project queries
    out: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name FROM projects WHERE tenant_id = %s ORDER BY id ASC",
            (tenant_id,),
        )
        projects = cur.fetchall()
        for pid, name in projects:
            cur.execute(
                """
                SELECT COUNT(*), MAX(created_at)
                FROM events
                WHERE project_id = %s AND deleted_at IS NULL AND status = 'active'
                """,
                (pid,),
            )
            cnt, last_ts = cur.fetchone()
            out.append(
                {
                    "project_id": pid,
                    "name": name,
                    "active_event_count": int(cnt or 0),
                    "last_event_at": last_ts,
                }
            )
    return out


def claim_next_job(conn: Any, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the highest-priority oldest pending job."""
    # Baseline bottleneck: blocks peer workers under lock contention
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM jobs
            WHERE status = 'pending'
            ORDER BY priority DESC, created_at ASC, id ASC
            LIMIT 1
            FOR UPDATE
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        jid = row[0]
        cur.execute(
            """
            UPDATE jobs
            SET status = 'processing', worker_id = %s, locked_at = now()
            WHERE id = %s
            RETURNING id, tenant_id, priority, worker_id, status
            """,
            (worker_id, jid),
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
    """Query projects under enforced app_user RLS for tenant_id + user_id."""
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


def list_tenant_event_feed_summary(
    conn: Any,
    tenant_id: int,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return newest active event summaries (id, project_id, kind, created_at) for tenant_id."""
    # Baseline bottleneck: triggers table heap fetches / sequential scan without covering index
    with conn.cursor() as cur:
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


def bulk_insert_events(conn: Any, rows: list[dict[str, Any]]) -> int:
    """Insert event dicts into events and return the number of inserted rows."""
    # Baseline bottleneck: row-by-row round-trip INSERT loop!
    if not rows:
        return 0
    with conn.cursor() as cur:
        for row in rows:
            payload = row["payload"]
            payload_json = payload if isinstance(payload, str) else json.dumps(payload)
            cur.execute(
                """
                INSERT INTO events (id, tenant_id, project_id, status, kind, payload, deleted_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    row["id"],
                    row["tenant_id"],
                    row["project_id"],
                    row["status"],
                    row["kind"],
                    payload_json,
                    row.get("deleted_at"),
                    row["created_at"],
                ),
            )
    return len(rows)
