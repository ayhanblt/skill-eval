"""Flawed calculator: uses float math and flat tier pricing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pricing_engine.models import Contract, InvoiceLineItem, InvoiceQuote, UsageRecord


def calculate_invoice(contract: Contract, usage: list[UsageRecord], *, as_of: date) -> InvoiceQuote:
    _ = as_of
    items = []
    sub = 0.0
    for rec in usage:
        entry = contract.catalog[rec.sku]
        rate = float(entry.tiers[-1].unit_price)
        for t in entry.tiers:
            if t.up_to is None or rec.quantity <= t.up_to:
                rate = float(t.unit_price)
                break
        amt = round(rec.quantity * rate, 2)
        sub += amt
        items.append(InvoiceLineItem(rec.sku, rec.quantity, Decimal(str(amt)), entry.taxable))
    d_sub = Decimal(f"{sub:.2f}")
    tax = Decimal(f"{round(float(d_sub) * float(contract.tax_rate_pct) / 100.0, 2):.2f}")
    return InvoiceQuote(
        contract_id=contract.contract_id,
        line_items=tuple(items),
        usage_subtotal=d_sub,
        minimum_true_up=Decimal("0.00"),
        gross_subtotal=d_sub,
        non_stackable_discount_code=None,
        discount_total=Decimal("0.00"),
        post_discount_subtotal=d_sub,
        credits_applied=Decimal("0.00"),
        remaining_credits=(),
        net_taxable_subtotal=d_sub,
        tax_amount=tax,
        total_due=d_sub + tax,
    )
