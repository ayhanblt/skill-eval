"""Multi-rule subscription, seat proration, allowance, adjustment & usage invoice calculator."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from pricing_engine.models import (
    Contract,
    DiscountRule,
    InvoiceLineItem,
    InvoiceQuote,
    PrepaidCredit,
    PricingValidationError,
    SkuCatalogEntry,
    UsageRecord,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


def _q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _validate_inputs(contract: Contract, usage: list[UsageRecord]) -> dict[str, int]:
    if contract.billing_period_days <= 0:
        raise PricingValidationError("billing_period_days must be positive")
    if contract.proration_days <= 0 or contract.proration_days > contract.billing_period_days:
        raise PricingValidationError("proration_days out of valid range")
    if contract.monthly_minimum < ZERO or contract.tax_rate_pct < ZERO:
        raise PricingValidationError("monthly_minimum and tax_rate_pct must be non-negative")
    if contract.credit_cap_pct < ZERO or contract.credit_cap_pct > HUNDRED:
        raise PricingValidationError("credit_cap_pct must be within [0, 100]")

    total_seg_days = 0
    for seg in contract.seat_segments:
        if seg.seats < 0 or seg.monthly_seat_price < ZERO or seg.active_days <= 0:
            raise PricingValidationError("Invalid SeatSegment")
        total_seg_days += seg.active_days
    if total_seg_days > contract.billing_period_days:
        raise PricingValidationError("seat_segments active_days sum exceeds billing_period_days")

    for adj in contract.adjustments:
        if not adj.code.strip():
            raise PricingValidationError("Adjustment code cannot be blank")

    for entry in contract.catalog.values():
        if not entry.tiers:
            raise PricingValidationError(f"SKU {entry.sku} has no tiers")
        if entry.included_units < 0:
            raise PricingValidationError(f"SKU {entry.sku} included_units cannot be negative")
        if entry.tier_mode not in ("GRADUATED", "VOLUME"):
            raise PricingValidationError(f"SKU {entry.sku} invalid tier_mode: {entry.tier_mode}")
        prev_up_to: int | None = 0
        for idx, tier in enumerate(entry.tiers):
            if tier.unit_price < ZERO:
                raise PricingValidationError("unit_price cannot be negative")
            if tier.up_to is None:
                if idx != len(entry.tiers) - 1:
                    raise PricingValidationError("Unbounded tier must be last")
            else:
                if tier.up_to <= 0 or (prev_up_to is not None and tier.up_to <= prev_up_to):
                    raise PricingValidationError("Tier boundaries must be strictly increasing")
                prev_up_to = tier.up_to

    for rule in contract.discounts:
        if rule.value < ZERO or rule.min_subtotal < ZERO:
            raise PricingValidationError("Discount value/min_subtotal cannot be negative")
        if rule.max_discount_amount is not None and rule.max_discount_amount < ZERO:
            raise PricingValidationError("Discount max_discount_amount cannot be negative")
        if rule.kind == "PCT" and rule.value > HUNDRED:
            raise PricingValidationError("Percentage discount cannot exceed 100")
        if rule.starts_on is not None and rule.ends_on is not None and rule.starts_on > rule.ends_on:
            raise PricingValidationError("Discount starts_on cannot be after ends_on")

    for credit in contract.credits:
        if credit.amount < ZERO:
            raise PricingValidationError("Prepaid credit amount cannot be negative")

    aggregated: dict[str, int] = {}
    for rec in usage:
        if rec.quantity < 0:
            raise PricingValidationError("Usage quantity cannot be negative")
        if rec.sku not in contract.catalog:
            raise PricingValidationError(f"Unknown SKU in usage: {rec.sku}")
        aggregated[rec.sku] = aggregated.get(rec.sku, 0) + rec.quantity
    return aggregated


def _price_sku(entry: SkuCatalogEntry, qty: int) -> Decimal:
    billable = max(0, qty - entry.included_units)
    if billable == 0:
        return ZERO
    if entry.tier_mode == "VOLUME":
        for tier in entry.tiers:
            if tier.up_to is None or billable <= tier.up_to:
                return _q2(Decimal(billable) * tier.unit_price)
        raise PricingValidationError(f"Quantity {billable} exceeds bounded tiers for SKU {entry.sku}")

    remaining = billable
    prev_cap = 0
    raw = ZERO
    for tier in entry.tiers:
        if remaining <= 0:
            break
        if tier.up_to is None:
            take = remaining
        else:
            take = min(remaining, tier.up_to - prev_cap)
            prev_cap = tier.up_to
        raw += Decimal(take) * tier.unit_price
        remaining -= take
    if remaining > 0:
        raise PricingValidationError(f"Quantity {billable} exceeds bounded tiers for SKU {entry.sku}")
    return _q2(raw)


def _rule_base(
    gross: Decimal, line_items: list[InvoiceLineItem], target_sku: str | None
) -> Decimal:
    if target_sku is None:
        return gross
    sku_sum = sum((li.amount for li in line_items if li.sku == target_sku), ZERO)
    return max(ZERO, min(gross, sku_sum))


def _rule_savings(base: Decimal, rule: DiscountRule) -> Decimal:
    if rule.kind == "FIXED":
        return min(base, _q2(rule.value))
    raw_pct = _q2(base * rule.value / HUNDRED)
    if rule.max_discount_amount is not None:
        raw_pct = min(raw_pct, _q2(rule.max_discount_amount))
    return min(base, raw_pct)


def _apply_discounts(
    gross: Decimal,
    line_items: list[InvoiceLineItem],
    rules: tuple[DiscountRule, ...],
    as_of: date,
) -> tuple[str | None, Decimal]:
    eligible = [
        r for r in rules
        if (r.starts_on is None or r.starts_on <= as_of)
        and (r.ends_on is None or as_of <= r.ends_on)
        and gross >= r.min_subtotal
    ]
    non_stack = [r for r in eligible if not r.stackable]
    ns_code: str | None = None
    ns_savings = ZERO
    if non_stack:
        candidates = [
            (_rule_savings(_rule_base(gross, line_items, r.target_sku), r), r.code)
            for r in non_stack
        ]
        candidates.sort(key=lambda pair: (-pair[0], pair[1]))
        ns_savings, ns_code = candidates[0]

    rem = max(ZERO, _q2(gross - ns_savings))
    stack = [r for r in eligible if r.stackable]

    uncapped_global_pct = min(
        HUNDRED,
        sum(
            (r.value for r in stack if r.kind == "PCT" and r.target_sku is None and r.max_discount_amount is None),
            Decimal("0"),
        ),
    )
    if uncapped_global_pct > Decimal("0"):
        rem = max(ZERO, _q2(rem - _q2(rem * uncapped_global_pct / HUNDRED)))

    for r in sorted(
        (r for r in stack if r.kind == "PCT" and r.target_sku is None and r.max_discount_amount is not None),
        key=lambda x: x.code,
    ):
        rem = max(ZERO, _q2(rem - _rule_savings(rem, r)))

    for r in sorted(
        (r for r in stack if r.kind == "PCT" and r.target_sku is not None),
        key=lambda x: x.code,
    ):
        base = min(rem, _rule_base(gross, line_items, r.target_sku))
        rem = max(ZERO, _q2(rem - _rule_savings(base, r)))

    fixed_sum = ZERO
    for r in stack:
        if r.kind != "FIXED":
            continue
        if r.target_sku is not None:
            fixed_sum += min(_rule_base(gross, line_items, r.target_sku), _q2(r.value))
        else:
            fixed_sum += _q2(r.value)
    post_discount = max(ZERO, _q2(rem - fixed_sum))
    return ns_code, post_discount


def _apply_credits(
    post_discount: Decimal,
    credits: tuple[PrepaidCredit, ...],
    as_of: date,
    credit_cap_pct: Decimal,
) -> tuple[Decimal, tuple[PrepaidCredit, ...]]:
    unexpired = sorted(
        (c for c in credits if c.amount > ZERO and c.expires_on >= as_of),
        key=lambda c: (c.expires_on, c.credit_id),
    )
    cap_amount = _q2(post_discount * credit_cap_pct / HUNDRED)
    need = min(post_discount, cap_amount)
    applied = ZERO
    remaining_list: list[PrepaidCredit] = []
    for c in unexpired:
        if need <= ZERO:
            remaining_list.append(c)
            continue
        use = min(need, _q2(c.amount))
        applied = _q2(applied + use)
        need = _q2(need - use)
        left = _q2(c.amount - use)
        if left > ZERO:
            remaining_list.append(PrepaidCredit(credit_id=c.credit_id, amount=left, expires_on=c.expires_on))
    return applied, tuple(remaining_list)


def calculate_invoice(
    contract: Contract,
    usage: list[UsageRecord],
    *,
    as_of: date,
) -> InvoiceQuote:
    aggregated = _validate_inputs(contract, usage)

    line_items = [
        InvoiceLineItem(
            sku=sku,
            quantity=aggregated[sku],
            amount=_price_sku(contract.catalog[sku], aggregated[sku]),
            taxable=contract.catalog[sku].taxable,
        )
        for sku in sorted(aggregated)
    ]
    for idx, seg in enumerate(contract.seat_segments, start=1):
        seg_amt = _q2(
            Decimal(seg.seats)
            * seg.monthly_seat_price
            * Decimal(seg.active_days)
            / Decimal(contract.billing_period_days)
        )
        line_items.append(
            InvoiceLineItem(
                sku=f"SEAT_PRORATION_{idx}",
                quantity=seg.seats,
                amount=seg_amt,
                taxable=seg.taxable,
            )
        )
    usage_subtotal = _q2(sum((li.amount for li in line_items), ZERO))

    adj_sum = ZERO
    for adj in contract.adjustments:
        amt = _q2(adj.amount)
        adj_sum += amt
        line_items.append(
            InvoiceLineItem(sku=f"ADJ_{adj.code}", quantity=1, amount=amt, taxable=adj.taxable)
        )
    pre_min_subtotal = max(ZERO, _q2(usage_subtotal + adj_sum))

    prorated_min = _q2(
        contract.monthly_minimum * Decimal(contract.proration_days) / Decimal(contract.billing_period_days)
    )
    minimum_true_up = _q2(prorated_min - pre_min_subtotal) if pre_min_subtotal < prorated_min else ZERO
    if minimum_true_up > ZERO:
        line_items.append(
            InvoiceLineItem(
                sku="MINIMUM_COMMIT_TRUE_UP",
                quantity=1,
                amount=minimum_true_up,
                taxable=True,
            )
        )

    gross_subtotal = max(ZERO, _q2(pre_min_subtotal + minimum_true_up))
    ns_code, post_discount_subtotal = _apply_discounts(
        gross_subtotal, line_items, contract.discounts, as_of
    )
    discount_total = _q2(gross_subtotal - post_discount_subtotal)

    credits_applied, remaining_credits = _apply_credits(
        post_discount_subtotal, contract.credits, as_of, contract.credit_cap_pct
    )
    post_credit_subtotal = _q2(post_discount_subtotal - credits_applied)

    raw_taxable_gross = max(
        ZERO,
        min(gross_subtotal, sum((li.amount for li in line_items if li.taxable), ZERO)),
    )
    if (
        contract.tax_exempt
        or gross_subtotal == ZERO
        or raw_taxable_gross == ZERO
        or contract.tax_rate_pct == Decimal("0")
    ):
        net_taxable_subtotal = ZERO
        tax_amount = ZERO
    else:
        net_taxable_subtotal = _q2(post_credit_subtotal * raw_taxable_gross / gross_subtotal)
        tax_amount = _q2(net_taxable_subtotal * contract.tax_rate_pct / HUNDRED)

    total_due = _q2(post_credit_subtotal + tax_amount)
    return InvoiceQuote(
        contract_id=contract.contract_id,
        line_items=tuple(line_items),
        usage_subtotal=usage_subtotal,
        minimum_true_up=minimum_true_up,
        gross_subtotal=gross_subtotal,
        non_stackable_discount_code=ns_code,
        discount_total=discount_total,
        post_discount_subtotal=post_discount_subtotal,
        credits_applied=credits_applied,
        remaining_credits=remaining_credits,
        net_taxable_subtotal=net_taxable_subtotal,
        tax_amount=tax_amount,
        total_due=total_due,
    )
