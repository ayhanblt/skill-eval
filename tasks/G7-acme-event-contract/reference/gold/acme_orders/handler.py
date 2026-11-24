"""Compliant Acme Order Ingestion service implementing acme.v2, idempotency & zero-PII audit."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from acme_orders.models import HttpResponse
from acme_orders.storage import OrderStorage


def _utc_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _header(headers: dict[str, str], name: str) -> str | None:
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            val = v.strip()
            return val if val else None
    return None


def _error_response(
    status: int,
    *,
    code: str,
    retryable: bool,
    correlation_id: str,
    message: str,
) -> HttpResponse:
    return HttpResponse(
        status=status,
        headers={"Content-Type": "application/json", "X-Correlation-Id": correlation_id},
        body={
            "error": {
                "code": code,
                "retryable": retryable,
                "correlation_id": correlation_id,
                "message": message,
            }
        },
    )


class AcmeOrderEventService:
    def __init__(self, data_dir: Path | str) -> None:
        self.storage = OrderStorage(data_dir)

    def handle_request(self, headers: dict[str, str], body: bytes) -> HttpResponse:
        correlation_id = _header(headers, "X-Correlation-Id") or str(uuid.uuid4())
        actor_id = _header(headers, "X-Actor-Id") or "anonymous"
        raw_sha256 = hashlib.sha256(body).hexdigest()

        # Parse JSON early to compute canonical hash if valid JSON
        parsed: Any = None
        payload_sha256 = raw_sha256
        json_valid = False
        try:
            parsed = json.loads(body.decode("utf-8"))
            if isinstance(parsed, dict):
                canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                payload_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                json_valid = True
        except Exception:
            json_valid = False

        idem_key = _header(headers, "X-Acme-Idempotency-Key")
        if not idem_key:
            self.storage.append_audit(
                actor_id=actor_id,
                action="order.ingest",
                outcome="rejected",
                payload_sha256=payload_sha256,
                correlation_id=correlation_id,
                error_code="ACME_EVT_400_MISSING_IDEMPOTENCY_KEY",
                recorded_at_utc=_utc_z(),
            )
            return _error_response(
                400,
                code="ACME_EVT_400_MISSING_IDEMPOTENCY_KEY",
                retryable=False,
                correlation_id=correlation_id,
                message="Missing required X-Acme-Idempotency-Key header.",
            )

        if not json_valid:
            self.storage.append_audit(
                actor_id=actor_id,
                action="order.ingest",
                outcome="rejected",
                payload_sha256=payload_sha256,
                correlation_id=correlation_id,
                error_code="ACME_EVT_400_INVALID_PAYLOAD",
                recorded_at_utc=_utc_z(),
            )
            return _error_response(
                400,
                code="ACME_EVT_400_INVALID_PAYLOAD",
                retryable=False,
                correlation_id=correlation_id,
                message="Request body must be a valid JSON object.",
            )

        existing = self.storage.get_idempotency(idem_key)
        if existing is not None:
            if existing["payload_sha256"] != payload_sha256:
                self.storage.append_audit(
                    actor_id=actor_id,
                    action="order.ingest",
                    outcome="rejected",
                    payload_sha256=payload_sha256,
                    correlation_id=correlation_id,
                    error_code="ACME_EVT_409_PAYLOAD_MISMATCH",
                    recorded_at_utc=_utc_z(),
                )
                return _error_response(
                    409,
                    code="ACME_EVT_409_PAYLOAD_MISMATCH",
                    retryable=False,
                    correlation_id=correlation_id,
                    message="Idempotency key reused with a different payload.",
                )

            self.storage.append_audit(
                actor_id=actor_id,
                action="order.ingest",
                outcome="replayed",
                payload_sha256=payload_sha256,
                correlation_id=correlation_id,
                error_code=None,
                recorded_at_utc=_utc_z(),
            )
            return HttpResponse(
                status=existing["response_status"],
                headers={
                    "Content-Type": "application/json",
                    "X-Acme-Replayed": "true",
                    "X-Correlation-Id": correlation_id,
                },
                body=existing["response_body"],
            )

        tenant_id = parsed.get("tenant_id")
        order_id = parsed.get("order_id")
        amount_cents = parsed.get("amount_cents")
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
            or not isinstance(order_id, str)
            or not order_id.strip()
            or isinstance(amount_cents, bool)
            or not isinstance(amount_cents, int)
            or amount_cents <= 0
        ):
            self.storage.append_audit(
                actor_id=actor_id,
                action="order.ingest",
                outcome="rejected",
                payload_sha256=payload_sha256,
                correlation_id=correlation_id,
                error_code="ACME_EVT_400_INVALID_PAYLOAD",
                recorded_at_utc=_utc_z(),
            )
            return _error_response(
                400,
                code="ACME_EVT_400_INVALID_PAYLOAD",
                retryable=False,
                correlation_id=correlation_id,
                message="Invalid or missing tenant_id, order_id, or positive integer amount_cents.",
            )

        envelope = {
            "schema_version": "acme.v2",
            "event_id": str(uuid.uuid4()),
            "correlation_id": correlation_id,
            "tenant_id": tenant_id,
            "order_id": order_id,
            "amount_cents": amount_cents,
            "event_type": str(parsed.get("event_type") or "order.submitted"),
            "occurred_at_utc": _utc_z(),
        }
        self.storage.save_accepted_event(envelope, idem_key, payload_sha256, 201, envelope)
        self.storage.append_audit(
            actor_id=actor_id,
            action="order.ingest",
            outcome="accepted",
            payload_sha256=payload_sha256,
            correlation_id=correlation_id,
            error_code=None,
            recorded_at_utc=_utc_z(),
        )
        return HttpResponse(
            status=201,
            headers={"Content-Type": "application/json", "X-Correlation-Id": correlation_id},
            body=envelope,
        )
