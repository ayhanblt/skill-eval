"""Validated webhook batch payload ingestion."""

from __future__ import annotations

from typing import Any

from billing_svc.models import BatchItem, PricingError


def parse_batch_payload(records: list[dict[str, Any]]) -> list[BatchItem]:
    """Validate and normalize raw webhook batch records into BatchItem instances."""
    items: list[BatchItem] = []
    for rec in records:
        raw_inv = rec.get("invoice_id")
        raw_tid = rec.get("tenant_id")
        if not isinstance(raw_inv, str) or not raw_inv.strip():
            raise PricingError("invoice_id must be a non-empty string")
        if not isinstance(raw_tid, str) or not raw_tid.strip():
            raise PricingError("tenant_id must be a non-empty string")

        raw_country = rec.get("country")
        norm_country: str | None = None
        if raw_country is not None:
            if not isinstance(raw_country, str) or not raw_country.strip():
                raise PricingError("country cannot be blank when provided")
            norm_country = raw_country.strip().upper()

        raw_quarter = rec.get("quarter", "2026Q1")
        if not isinstance(raw_quarter, str) or not raw_quarter.strip():
            raise PricingError("quarter must be non-empty")
        norm_quarter = raw_quarter.strip().upper()

        items.append(
            BatchItem(
                invoice_id=raw_inv.strip(),
                tenant_id=raw_tid.strip(),
                seats=int(rec["seats"]),
                country=norm_country,
                quarter=norm_quarter,
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
