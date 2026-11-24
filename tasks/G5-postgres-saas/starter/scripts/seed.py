#!/usr/bin/env python3
"""Deterministic high-speed dataset seeder for G5 PostgreSQL SaaS benchmark."""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone
import psycopg2


def get_dsn() -> str:
    return os.environ.get("PG_DSN", "dbname=saas_eval user=postgres host=/tmp port=5433")


def seed(conn) -> None:
    base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE jobs, events, projects, users, tenants RESTART IDENTITY CASCADE;")

        # 20 tenants
        buf = io.StringIO()
        for tid in range(1, 21):
            plan = "enterprise" if tid % 4 == 0 else "pro"
            buf.write(f"{tid}\ttenant-{tid:02d}\t{plan}\t{base_ts.isoformat()}\n")
        buf.seek(0)
        cur.copy_from(buf, "tenants", columns=("id", "slug", "plan", "created_at"))

        # 200 users (10 per tenant)
        buf = io.StringIO()
        uid = 1
        for tid in range(1, 21):
            for u in range(10):
                role = "admin" if u == 0 else "member"
                buf.write(f"{uid}\t{tid}\tuser{uid}@t{tid}.example\t{role}\t{base_ts.isoformat()}\n")
                uid += 1
        buf.seek(0)
        cur.copy_from(buf, "users", columns=("id", "tenant_id", "email", "role", "created_at"))

        # 400 projects (20 per tenant; every 20th project has ZERO active events!)
        buf = io.StringIO()
        pid = 1
        zero_event_projects: set[int] = set()
        for tid in range(1, 21):
            first_uid = (tid - 1) * 10 + 1
            for p_idx in range(20):
                owner_id = first_uid + (p_idx % 10)
                is_priv = "t" if p_idx % 4 == 0 else "f"
                buf.write(f"{pid}\t{tid}\t{owner_id}\tProject {pid}\t{is_priv}\t{base_ts.isoformat()}\n")
                if p_idx == 19:
                    zero_event_projects.add(pid)
                pid += 1
        buf.seek(0)
        cur.copy_from(buf, "projects", columns=("id", "tenant_id", "owner_id", "name", "is_private", "created_at"))

        # 80,000 events (~70% archived or soft-deleted, ~30% active)
        buf = io.StringIO()
        kinds = ("deploy", "error", "billing", "audit")
        for eid in range(1, 80_001):
            tid = ((eid - 1) % 20) + 1
            # Pick among first 19 projects of tenant so project #20 stays at 0 events
            p_offset = ((eid - 1) // 20) % 19
            proj_id = (tid - 1) * 20 + 1 + p_offset
            ts = base_ts + timedelta(seconds=eid * 15)
            mod10 = eid % 10
            if mod10 < 3:
                status = "active"
                deleted = "\\N"
            elif mod10 < 7:
                status = "archived"
                deleted = "\\N"
            else:
                status = "active"
                deleted = (ts + timedelta(hours=1)).isoformat()
            kind = kinds[eid % 4]
            buf.write(f"{eid}\t{tid}\t{proj_id}\t{status}\t{kind}\t{{}}\t{deleted}\t{ts.isoformat()}\n")
        buf.seek(0)
        cur.copy_from(
            buf,
            "events",
            columns=("id", "tenant_id", "project_id", "status", "kind", "payload", "deleted_at", "created_at"),
        )

        # 5,000 jobs (4,500 completed, 500 pending)
        buf = io.StringIO()
        for jid in range(1, 5_001):
            tid = ((jid - 1) % 20) + 1
            status = "pending" if jid > 4_500 else "completed"
            prio = (jid % 10)
            worker = "\\N" if status == "pending" else f"worker-{jid % 4}"
            ts = base_ts + timedelta(seconds=jid * 20)
            buf.write(f"{jid}\t{tid}\t{status}\t{prio}\t{worker}\t{{}}\t{ts.isoformat()}\n")
        buf.seek(0)
        cur.copy_from(
            buf,
            "jobs",
            columns=("id", "tenant_id", "status", "priority", "worker_id", "payload", "created_at"),
        )
        with conn.cursor() as cur:
            cur.execute("ANALYZE;")
    conn.commit()


if __name__ == "__main__":
    with psycopg2.connect(get_dsn()) as connection:
        seed(connection)
    print("Seeded 20 tenants, 200 users, 400 projects, 80,000 events, 5,000 jobs.")
