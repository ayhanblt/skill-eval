"""Flawed calculator: forgets credit expiration check and relies on weak smoke tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from pricing_engine.models import (
    Contract, InvoiceLineItem, InvoiceQuote, PrepaidCredit, PricingValidationError, UsageRecord,
)

CENT = Decimal("0.01")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_invoice(contract: Contract, usage: list[UsageRecord], *, as_of: date) -> InvoiceQuote:
    _ = as_of
    if contract.billing_period_days <= 0 or contract.proration_days <= 0 or contract.proration_days > contract.billing_period_days:
        raise PricingValidationError("invalid proration")
    agg: dict[str, int] = {}
    for r in usage:
        if r.quantity < 0 or r.sku not in contract.catalog:
            raise PricingValidationError("invalid usage")
        agg[r.sku] = agg.get(r.sku, 0) + r.quantity
    items = []
    for sku in sorted(agg):
        entry = contract.catalog[sku]
        rem, prev, raw = agg[sku], 0, Decimal("0")
        for t in entry.tiers:
            if rem <= 0:
                break
            take = rem if t.up_to is None else min(rem, t.up_to - prev)
            raw += Decimal(take) * t.unit_price
            rem -= take
            if t.up_to is not None:
                prev = t.up_to
        items.append(InvoiceLineItem(sku, agg[sku], _q2(raw), entry.taxable))
    sub = _q2(sum((i.amount for i in items), Decimal("0.00")))
    # Bug: applies expired credits!
    cred = min(sub, sum((_q2(c.amount) for c in contract.credits), Decimal("0.00")))
    post = _q2(sub - cred)
    tax = Decimal("0.00") if contract.tax_exempt else _q2(post * contract.tax_rate_pct / Decimal("100"))
    return InvoiceQuote(
        contract_id=contract.contract_id,
        line_items=tuple(items),
        usage_subtotal=sub,
        minimum_true_up=Decimal("0.00"),
        gross_subtotal=sub,
        non_stackable_discount_code=None,
        discount_total=Decimal("0.00"),
        post_discount_subtotal=sub,
        credits_applied=cred,
        remaining_credits=(),
        net_taxable_subtotal=post,
        tax_amount=tax,
        total_due=_q2(post + tax),
    )
