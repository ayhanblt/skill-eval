"""Multi-rule subscription & usage invoice calculator."""

from __future__ import annotations

from datetime import date

from pricing_engine.models import Contract, InvoiceQuote, UsageRecord


def calculate_invoice(
    contract: Contract,
    usage: list[UsageRecord],
    *,
    as_of: date,
) -> InvoiceQuote:
    raise NotImplementedError("Implement calculate_invoice according to SPEC.md")
