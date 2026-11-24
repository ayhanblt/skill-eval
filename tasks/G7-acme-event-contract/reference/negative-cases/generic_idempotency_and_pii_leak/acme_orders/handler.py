"""Flawed handler: accepts generic Idempotency-Key, emits +00:00, flat errors, leaks PII in audit."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from acme_orders.models import HttpResponse
from acme_orders.storage import OrderStorage


class AcmeOrderEventService:
    def __init__(self, data_dir: Path | str) -> None:
        self.storage = OrderStorage(data_dir)

    def handle_request(self, headers: dict[str, str], body: bytes) -> HttpResponse:
        low = {k.lower(): v for k, v in headers.items()}
        key = low.get("x-acme-idempotency-key") or low.get("idempotency-key")
        if not key:
            return HttpResponse(status=400, body={"detail": "missing idempotency key"})
        data = json.loads(body.decode("utf-8"))
        sha = hashlib.sha256(body).hexdigest()
        existing = self.storage.get_idempotency(key)
        if existing:
            if existing["payload_sha256"] != sha:
                return HttpResponse(status=409, body={"detail": "conflict"})
            return HttpResponse(status=200, body=existing["response_body"])

        env = {
            "schema_version": "acme.v2",
            "event_id": str(uuid.uuid4()),
            "correlation_id": low.get("x-correlation-id", str(uuid.uuid4())),
            "tenant_id": data["tenant_id"],
            "order_id": data["order_id"],
            "amount_cents": data["amount_cents"],
            "occurred_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        self.storage.save_accepted_event(env, key, sha, 201, env)
        # Leaks raw PII directly into audit.jsonl!
        with self.storage.audit_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"raw_body": data, "auth": low.get("authorization")}) + "\n")
        return HttpResponse(status=201, body=env)
