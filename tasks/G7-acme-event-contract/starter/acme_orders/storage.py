"""SQLite + append-only JSONL persistence layer for Acme Order Ingestion."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class OrderStorage:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "orders.db"
        self.audit_log_path = self.data_dir / "audit.jsonl"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                  event_id TEXT PRIMARY KEY,
                  schema_version TEXT NOT NULL,
                  correlation_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  order_id TEXT NOT NULL,
                  amount_cents INTEGER NOT NULL,
                  occurred_at_utc TEXT NOT NULL,
                  envelope_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency_records (
                  idempotency_key TEXT PRIMARY KEY,
                  payload_sha256 TEXT NOT NULL,
                  response_status INTEGER NOT NULL,
                  response_body_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  actor_id TEXT NOT NULL,
                  action TEXT NOT NULL,
                  outcome TEXT NOT NULL,
                  payload_sha256 TEXT NOT NULL,
                  correlation_id TEXT NOT NULL,
                  error_code TEXT,
                  recorded_at_utc TEXT NOT NULL
                );
                """
            )

    def get_idempotency(self, key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT idempotency_key, payload_sha256, response_status, response_body_json "
                "FROM idempotency_records WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "idempotency_key": row["idempotency_key"],
            "payload_sha256": row["payload_sha256"],
            "response_status": int(row["response_status"]),
            "response_body": json.loads(row["response_body_json"]),
        }

    def save_accepted_event(
        self,
        envelope: dict[str, Any],
        idempotency_key: str,
        payload_sha256: str,
        response_status: int,
        response_body: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (
                  event_id, schema_version, correlation_id, tenant_id,
                  order_id, amount_cents, occurred_at_utc, envelope_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    envelope["event_id"],
                    envelope["schema_version"],
                    envelope["correlation_id"],
                    envelope["tenant_id"],
                    envelope["order_id"],
                    int(envelope["amount_cents"]),
                    envelope["occurred_at_utc"],
                    json.dumps(envelope, sort_keys=True),
                ),
            )
            conn.execute(
                """
                INSERT INTO idempotency_records (
                  idempotency_key, payload_sha256, response_status, response_body_json
                ) VALUES (?, ?, ?, ?)
                """,
                (idempotency_key, payload_sha256, response_status, json.dumps(response_body)),
            )

    def append_audit(
        self,
        *,
        actor_id: str,
        action: str,
        outcome: str,
        payload_sha256: str,
        correlation_id: str,
        error_code: str | None,
        recorded_at_utc: str,
    ) -> None:
        record = {
            "actor_id": actor_id,
            "action": action,
            "outcome": outcome,
            "payload_sha256": payload_sha256,
            "correlation_id": correlation_id,
            "error_code": error_code,
            "recorded_at_utc": recorded_at_utc,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                  actor_id, action, outcome, payload_sha256,
                  correlation_id, error_code, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    actor_id,
                    action,
                    outcome,
                    payload_sha256,
                    correlation_id,
                    error_code,
                    recorded_at_utc,
                ),
            )
        with self.audit_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def count_events(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
            return int(row[0]) if row else 0
