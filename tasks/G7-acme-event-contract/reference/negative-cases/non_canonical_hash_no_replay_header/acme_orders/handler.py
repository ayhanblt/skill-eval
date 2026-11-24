"""Flawed handler: hashes raw bytes instead of canonical JSON, omits X-Acme-Replayed, skips audit on errors."""

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
        corr = low.get("x-correlation-id") or str(uuid.uuid4())
        key = low.get("x-acme-idempotency-key")
        if not key:
            return HttpResponse(
                status=400,
                body={"error": {"code": "ACME_EVT_400_MISSING_IDEMPOTENCY_KEY", "retryable": False, "correlation_id": corr, "message": "Missing header"}},
            )
        raw_sha = hashlib.sha256(body).hexdigest()
        existing = self.storage.get_idempotency(key)
        if existing:
            if existing["payload_sha256"] != raw_sha:
                return HttpResponse(
                    status=409,
                    body={"error": {"code": "ACME_EVT_409_PAYLOAD_MISMATCH", "retryable": False, "correlation_id": corr, "message": "Conflict"}},
                )
            return HttpResponse(status=existing["response_status"], body=existing["response_body"])

        data = json.loads(body.decode("utf-8"))
        if int(data.get("amount_cents", 0)) <= 0:
            return HttpResponse(
                status=400,
                body={"error": {"code": "ACME_EVT_400_INVALID_PAYLOAD", "retryable": False, "correlation_id": corr, "message": "Invalid"}},
            )
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        env = {
            "schema_version": "acme.v2",
            "event_id": str(uuid.uuid4()),
            "correlation_id": corr,
            "tenant_id": data["tenant_id"],
            "order_id": data["order_id"],
            "amount_cents": data["amount_cents"],
            "occurred_at_utc": ts,
        }
        self.storage.save_accepted_event(env, key, raw_sha, 201, env)
        self.storage.append_audit(
            actor_id=low.get("x-actor-id", "anonymous"),
            action="order.ingest",
            outcome="accepted",
            payload_sha256=raw_sha,
            correlation_id=corr,
            error_code=None,
            recorded_at_utc=ts,
        )
        return HttpResponse(status=201, body=env)
