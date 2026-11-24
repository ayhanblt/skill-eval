"""Webhook batch payload ingestion for billing runner."""

from __future__ import annotations

from typing import Any

from billing_svc.models import BatchItem


def parse_batch_payload(records: list[dict[str, Any]]) -> list[BatchItem]:
    """Convert raw webhook batch JSON objects into BatchItem instances."""
    items: list[BatchItem] = []
    for rec in records:
        items.append(
            BatchItem(
                invoice_id=str(rec["invoice_id"]),
                tenant_id=str(rec["tenant_id"]),
                seats=int(rec["seats"]),
                country=rec.get("country"),
                quarter=str(rec.get("quarter", "2026Q1")),
                tax_exempt=bool(rec.get("tax_exempt", False)),
                promo_code=rec.get("promo_code"),
                grant_credit_cents=int(rec.get("grant_credit_cents", 0)),
                ledger_credit_cents=int(rec.get("ledger_credit_cents", 0)),
                payment_cents=(
                    int(rec["payment_cents"]) if rec.get("payment_cents") is not None else None
                ),
            )
        )
    return items
