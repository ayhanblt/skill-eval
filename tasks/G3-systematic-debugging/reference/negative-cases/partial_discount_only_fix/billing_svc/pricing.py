"""Partial fix: copies discounts dict only, leaving feature_credits, tax_engine, and batch rollback broken."""

from __future__ import annotations

from billing_svc.cache import TenantPolicyCache
from billing_svc.currency import apply_bps, compute_tax_cents
from billing_svc.models import Invoice, PricingError
from billing_svc.tax_engine import TaxEngine

PROMO_CATALOG_BPS: dict[str, int] = {
    "ANNUAL20": 2000,
    "PARTNER10": 1000,
    "LAUNCH15": 1500,
}


def generate_invoice(
    invoice_id: str,
    tenant_id: str,
    seats: int,
    *,
    promo_code: str | None = None,
    grant_credit_cents: int = 0,
    ledger_credit_cents: int = 0,
    country: str | None = None,
    quarter: str = "2026Q1",
    tax_exempt: bool = False,
    cache: TenantPolicyCache | None = None,
    tax_engine: TaxEngine | None = None,
) -> Invoice:
    if seats <= 0:
        raise PricingError("seats must be positive")
    policy_cache = cache or TenantPolicyCache()
    policy = policy_cache.get_policy(tenant_id)
    discounts = dict(policy["discounts"])
    if promo_code:
        discounts[promo_code] = PROMO_CATALOG_BPS[promo_code]
    if grant_credit_cents > 0:
        policy["feature_credits"].append(grant_credit_cents)

    subtotal = seats * int(policy["base_rate_cents"])
    best_bps = max(discounts.values(), default=0)
    discount_cents = apply_bps(subtotal, min(best_bps, 10_000))
    after_discount = max(0, subtotal - discount_cents)
    raw_credits = sum(int(c) for c in policy["feature_credits"]) + int(ledger_credit_cents)
    credit_cents = min(after_discount, raw_credits)
    taxable = max(0, after_discount - credit_cents)
    if country is not None or tax_exempt:
        engine = tax_engine or TaxEngine()
        sched = engine.resolve_rate(country or "US", quarter, tax_exempt=tax_exempt)
        if tax_exempt:
            sched["tax_bps"] = 0
        eff_bps = int(sched["tax_bps"])
    else:
        eff_bps = int(policy["tax_bps"])
    tax_cents = compute_tax_cents(taxable, eff_bps)
    return Invoice(
        invoice_id=invoice_id,
        tenant_id=tenant_id,
        seats=seats,
        subtotal_cents=subtotal,
        discount_cents=discount_cents,
        credit_cents=credit_cents,
        tax_cents=tax_cents,
        total_cents=taxable + tax_cents,
        applied_promos=tuple(sorted(discounts.keys())),
    )
