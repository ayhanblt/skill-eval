"""Hidden deterministic grader + 20-mutant suite for G4-tdd-feature."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from skilleval.grader_utils import run_in_sandbox
from skilleval.schemas import CheckOutcome, GateResults, GradeResult

MUTANTS_PY = r"""
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from pricing_engine.models import (
    Contract, DiscountRule, InvoiceLineItem, InvoiceQuote, PrepaidCredit, PricingValidationError, UsageRecord,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")

def q2(v: Decimal, rounding=ROUND_HALF_UP) -> Decimal:
    return v.quantize(CENT, rounding=rounding)

def make_mutant(mode: str):
    rounding = ROUND_HALF_EVEN if mode == "M7_bankers_rounding" else ROUND_HALF_UP
    def calculate_invoice(contract: Contract, usage: list[UsageRecord], *, as_of: date) -> InvoiceQuote:
        if contract.billing_period_days <= 0 or contract.proration_days <= 0 or contract.proration_days > contract.billing_period_days:
            raise PricingValidationError("invalid proration")
        if contract.monthly_minimum < 0 or contract.tax_rate_pct < 0:
            raise PricingValidationError("negative contract config")
        cap_pct = getattr(contract, "credit_cap_pct", HUNDRED)
        if mode != "M20_validation_missing_bounds" and (cap_pct < ZERO or cap_pct > HUNDRED):
            raise PricingValidationError("invalid credit_cap_pct")
        seg_days = 0
        for seg in getattr(contract, "seat_segments", ()):
            if seg.seats < 0 or seg.monthly_seat_price < ZERO or seg.active_days <= 0:
                raise PricingValidationError("invalid seat segment")
            seg_days += seg.active_days
        if mode != "M11_seat_segments_combined_before_round" and seg_days > contract.billing_period_days:
            raise PricingValidationError("seat days exceed billing_period_days")
        for adj in getattr(contract, "adjustments", ()):
            if not adj.code.strip():
                raise PricingValidationError("blank adj code")
        for entry in contract.catalog.values():
            if not entry.tiers:
                raise PricingValidationError("no tiers")
            if mode != "M20_validation_missing_bounds" and getattr(entry, "included_units", 0) < 0:
                raise PricingValidationError("negative included_units")
            if getattr(entry, "tier_mode", "GRADUATED") not in ("GRADUATED", "VOLUME"):
                raise PricingValidationError("invalid tier_mode")
        for r in contract.discounts:
            if r.value < ZERO or r.min_subtotal < ZERO:
                raise PricingValidationError("negative discount")
            if mode != "M20_validation_missing_bounds":
                if r.max_discount_amount is not None and r.max_discount_amount < ZERO:
                    raise PricingValidationError("negative cap")
                if r.starts_on is not None and r.ends_on is not None and r.starts_on > r.ends_on:
                    raise PricingValidationError("bad discount dates")

        agg: dict[str, int] = {}
        for rec in usage:
            if mode != "M6_negative_usage_accepted" and rec.quantity < 0:
                raise PricingValidationError("negative quantity")
            if rec.sku not in contract.catalog:
                raise PricingValidationError("unknown sku")
            agg[rec.sku] = agg.get(rec.sku, 0) + rec.quantity

        items: list[InvoiceLineItem] = []
        for sku in sorted(agg):
            entry = contract.catalog[sku]
            qty = agg[sku]
            inc = 0 if mode == "M13_included_units_ignored" else getattr(entry, "included_units", 0)
            billable = max(0, qty - inc)
            tmode = getattr(entry, "tier_mode", "GRADUATED")
            if billable == 0:
                amt = ZERO
            elif mode == "M1_flat_tier" or (tmode == "VOLUME" and mode != "M14_volume_mode_uses_graduated"):
                picked = None
                for t in entry.tiers:
                    if t.up_to is None or billable <= t.up_to:
                        picked = t.unit_price
                        break
                if picked is None:
                    raise PricingValidationError("exceeds bounded tiers")
                amt = q2(Decimal(billable) * picked, rounding)
            else:
                rem = billable
                prev = 0
                raw = Decimal("0")
                for t in entry.tiers:
                    if rem <= 0:
                        break
                    take = rem if t.up_to is None else min(rem, t.up_to - prev)
                    raw += Decimal(take) * t.unit_price
                    rem -= take
                    if t.up_to is not None:
                        prev = t.up_to
                if rem > 0:
                    raise PricingValidationError("exceeds bounded tiers")
                amt = q2(raw, rounding)
            items.append(InvoiceLineItem(sku=sku, quantity=qty, amount=amt, taxable=entry.taxable))

        if mode == "M11_seat_segments_combined_before_round" and getattr(contract, "seat_segments", ()):
            raw_seg = sum(
                (Decimal(s.seats) * s.monthly_seat_price * Decimal(s.active_days) / Decimal(contract.billing_period_days)
                 for s in contract.seat_segments),
                ZERO,
            )
            items.append(InvoiceLineItem("SEAT_PRORATION_1", sum(s.seats for s in contract.seat_segments), q2(raw_seg, rounding), True))
        else:
            for idx, seg in enumerate(getattr(contract, "seat_segments", ()), start=1):
                seg_amt = q2(Decimal(seg.seats) * seg.monthly_seat_price * Decimal(seg.active_days) / Decimal(contract.billing_period_days), rounding)
                items.append(InvoiceLineItem(f"SEAT_PRORATION_{idx}", seg.seats, seg_amt, seg.taxable))

        usage_sub = q2(sum((i.amount for i in items), ZERO), rounding)
        adj_sum = ZERO
        for adj in getattr(contract, "adjustments", ()):
            a_amt = q2(adj.amount, rounding)
            adj_sum += a_amt
            items.append(InvoiceLineItem(f"ADJ_{adj.code}", 1, a_amt, adj.taxable))

        prorated_min = q2(contract.monthly_minimum * Decimal(contract.proration_days) / Decimal(contract.billing_period_days), rounding)
        if mode == "M12_adjustments_after_minimum_true_up":
            true_up = q2(prorated_min - usage_sub, rounding) if usage_sub < prorated_min else ZERO
            if true_up > ZERO:
                items.append(InvoiceLineItem("MINIMUM_COMMIT_TRUE_UP", 1, true_up, True))
            gross = max(ZERO, q2(usage_sub + true_up + adj_sum, rounding))
        else:
            pre_min = max(ZERO, q2(usage_sub + adj_sum, rounding))
            true_up = q2(prorated_min - pre_min, rounding) if pre_min < prorated_min else ZERO
            if true_up > ZERO:
                items.append(InvoiceLineItem("MINIMUM_COMMIT_TRUE_UP", 1, true_up, True))
            gross = max(ZERO, q2(pre_min + true_up, rounding))

        active = [
            d for d in contract.discounts
            if (d.starts_on is None or d.starts_on <= as_of)
            and (d.ends_on is None or as_of <= d.ends_on)
            and (
                (gross > getattr(d, "min_subtotal", ZERO))
                if mode == "M10_min_subtotal_strict_gt"
                else (gross >= getattr(d, "min_subtotal", ZERO))
            )
        ]

        def _base(target_sku):
            if target_sku is None or mode == "M9_sku_discount_applied_globally":
                return gross
            return max(ZERO, min(gross, sum((i.amount for i in items if i.sku == target_sku), ZERO)))

        def _sav(base, rule):
            if rule.kind == "FIXED":
                return min(base, q2(rule.value, rounding))
            s = q2(base * rule.value / HUNDRED, rounding)
            cap = getattr(rule, "max_discount_amount", None)
            if cap is not None and mode != "M15_discount_cap_ignored_in_selection":
                s = min(s, q2(cap, rounding))
            return min(base, s)

        non_stack = [d for d in active if not d.stackable]
        ns_code = None
        ns_save = ZERO
        if non_stack:
            if mode == "M3_wrong_non_stackable":
                d0 = non_stack[0]
                ns_code = d0.code
                ns_save = _sav(_base(getattr(d0, "target_sku", None)), d0)
            else:
                best = None
                for d in non_stack:
                    s = _sav(_base(getattr(d, "target_sku", None)), d)
                    if mode == "M16_discount_tiebreak_wrong_order":
                        key = (s, tuple(ord(c) for c in d.code))
                    else:
                        key = (s, tuple(-ord(c) for c in d.code))
                    if best is None or key > best[0]:
                        best = (key, d.code, s)
                _, ns_code, ns_save = best

        rem = max(ZERO, q2(gross - ns_save, rounding))
        stack = [d for d in active if d.stackable]
        pct_sum = min(
            HUNDRED,
            sum(
                (
                    d.value
                    for d in stack
                    if d.kind == "PCT"
                    and getattr(d, "target_sku", None) is None
                    and (mode == "M15_discount_cap_ignored_in_selection" or getattr(d, "max_discount_amount", None) is None)
                ),
                Decimal("0"),
            ),
        )
        if pct_sum > Decimal("0"):
            rem = max(ZERO, q2(rem - q2(rem * pct_sum / HUNDRED, rounding), rounding))
        if mode != "M15_discount_cap_ignored_in_selection":
            for d in sorted(
                (d for d in stack if d.kind == "PCT" and getattr(d, "target_sku", None) is None and getattr(d, "max_discount_amount", None) is not None),
                key=lambda x: x.code,
            ):
                rem = max(ZERO, q2(rem - _sav(rem, d), rounding))
        for d in sorted((d for d in stack if d.kind == "PCT" and getattr(d, "target_sku", None) is not None), key=lambda x: x.code):
            b = min(rem, _base(d.target_sku))
            rem = max(ZERO, q2(rem - _sav(b, d), rounding))
        fixed_sum = ZERO
        for d in stack:
            if d.kind != "FIXED":
                continue
            tsku = getattr(d, "target_sku", None)
            if tsku is not None and mode != "M9_sku_discount_applied_globally":
                fixed_sum += min(_base(tsku), q2(d.value, rounding))
            else:
                fixed_sum += q2(d.value, rounding)
        post_disc = max(ZERO, q2(rem - fixed_sum, rounding))
        disc_total = q2(gross - post_disc, rounding)

        creds = [
            c for c in contract.credits
            if c.amount > ZERO and (
                mode == "M2_expired_credit"
                or (c.expires_on > as_of if mode == "M8_credit_expiry_off_by_one" else c.expires_on >= as_of)
            )
        ]
        if mode == "M17_credit_fifo_same_date_tiebreak":
            creds.sort(key=lambda c: (c.expires_on, tuple(-ord(ch) for ch in c.credit_id)))
        else:
            creds.sort(key=lambda c: (c.expires_on, c.credit_id))

        eff_cap = HUNDRED if mode == "M18_credit_cap_pct_ignored" else cap_pct
        if mode == "M4_negative_subtotal_credits":
            applied = q2(sum((c.amount for c in creds), ZERO), rounding)
            rem_creds = ()
            post_cred = q2(post_disc - applied, rounding)
        else:
            need = min(post_disc, q2(post_disc * eff_cap / HUNDRED, rounding))
            applied = ZERO
            rem_list = []
            for c in creds:
                if need <= ZERO:
                    rem_list.append(c)
                    continue
                use = min(need, q2(c.amount, rounding))
                applied = q2(applied + use, rounding)
                need = q2(need - use, rounding)
                left = q2(c.amount - use, rounding)
                if left > ZERO:
                    rem_list.append(PrepaidCredit(credit_id=c.credit_id, amount=left, expires_on=c.expires_on))
            rem_creds = tuple(rem_list)
            post_cred = q2(post_disc - applied, rounding)

        if mode == "M5_tax_non_taxable":
            tax_sum = sum((i.amount for i in items), ZERO)
        elif mode == "M19_negative_taxable_adj_ignored_in_tax_base":
            tax_sum = sum((max(ZERO, i.amount) for i in items if i.taxable), ZERO)
        else:
            tax_sum = sum((i.amount for i in items if i.taxable), ZERO)
        raw_tax_gross = max(ZERO, min(gross, tax_sum))
        if contract.tax_exempt or gross == ZERO or raw_tax_gross == ZERO or contract.tax_rate_pct == Decimal("0"):
            net_taxable = ZERO
            tax_amt = ZERO
        else:
            net_taxable = q2(post_cred * raw_tax_gross / gross, rounding)
            tax_amt = q2(net_taxable * contract.tax_rate_pct / HUNDRED, rounding)
        total_due = q2(post_cred + tax_amt, rounding)
        return InvoiceQuote(
            contract_id=contract.contract_id,
            line_items=tuple(items),
            usage_subtotal=usage_sub,
            minimum_true_up=true_up,
            gross_subtotal=gross,
            non_stackable_discount_code=ns_code,
            discount_total=disc_total,
            post_discount_subtotal=post_disc,
            credits_applied=applied,
            remaining_credits=rem_creds,
            net_taxable_subtotal=net_taxable,
            tax_amount=tax_amt,
            total_due=total_due,
        )
    return calculate_invoice
"""

CONTAINER_SCRIPT = r"""
import copy
import json
import os
import shutil
import subprocess
import sys
import time
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/grade_scripts")

OUT_DIR = Path("/grade_out")


def run_hidden_tests() -> dict:
    from pricing_engine.calculator import calculate_invoice
    from pricing_engine.models import (
        Adjustment, Contract, DiscountRule, InvoiceQuote, PrepaidCredit,
        PricingValidationError, SeatSegment, SkuCatalogEntry, UsageRecord, VolumeTier,
    )

    results = {}

    def check(name, fn):
        try:
            fn()
            results[name] = {"passed": True, "detail": "ok"}
        except Exception as exc:
            results[name] = {"passed": False, "detail": f"{type(exc).__name__}: {exc}"}

    base_cat = {
        "API": SkuCatalogEntry(
            sku="API",
            tiers=(
                VolumeTier(up_to=1000, unit_price=Decimal("0.10")),
                VolumeTier(up_to=5000, unit_price=Decimal("0.08")),
                VolumeTier(up_to=None, unit_price=Decimal("0.05")),
            ),
            taxable=True,
        ),
        "PRO_SUPPORT": SkuCatalogEntry(
            sku="PRO_SUPPORT",
            tiers=(VolumeTier(up_to=None, unit_price=Decimal("25.00")),),
            taxable=False,
        ),
    }

    def t_graduated_and_aggregation():
        c = Contract(contract_id="c1", catalog=base_cat, tax_rate_pct=Decimal("10.00"))
        q = calculate_invoice(c, [UsageRecord("API", 2000), UsageRecord("API", 4000)], as_of=date(2026, 6, 1))
        assert q.usage_subtotal == Decimal("470.00"), q
        assert q.tax_amount == Decimal("47.00"), q
        assert q.total_due == Decimal("517.00"), q
        assert all(isinstance(x, Decimal) for x in [q.usage_subtotal, q.tax_amount, q.total_due])

    def t_half_up_rounding():
        cat = {"U": SkuCatalogEntry("U", (VolumeTier(None, Decimal("1.005")),))}
        c = Contract(contract_id="c2", catalog=cat, tax_rate_pct=Decimal("5.00"))
        q = calculate_invoice(c, [UsageRecord("U", 5)], as_of=date(2026, 6, 1))
        assert q.usage_subtotal == Decimal("5.03"), q.usage_subtotal
        assert q.tax_amount == Decimal("0.25"), q.tax_amount

    def t_minimum_proration_true_up():
        c = Contract(
            contract_id="c3",
            catalog=base_cat,
            monthly_minimum=Decimal("300.00"),
            billing_period_days=30,
            proration_days=15,
            tax_rate_pct=Decimal("8.00"),
        )
        q = calculate_invoice(c, [UsageRecord("API", 100)], as_of=date(2026, 6, 1))
        assert q.minimum_true_up == Decimal("140.00"), q
        assert q.gross_subtotal == Decimal("150.00"), q
        assert any(li.sku == "MINIMUM_COMMIT_TRUE_UP" and li.amount == Decimal("140.00") for li in q.line_items)
        assert q.tax_amount == Decimal("12.00")

    def t_discounts_tiebreak_and_stackable():
        c = Contract(
            contract_id="c4",
            catalog=base_cat,
            discounts=(
                DiscountRule("ZETA_10", "PCT", Decimal("10"), stackable=False),
                DiscountRule("BETA_20", "FIXED", Decimal("20.00"), stackable=False),
                DiscountRule("ALPHA_10", "PCT", Decimal("10"), stackable=False),
                DiscountRule("EXPIRED_50", "PCT", Decimal("50"), stackable=False, ends_on=date(2026, 5, 31)),
                DiscountRule("LOYAL_10", "PCT", Decimal("10"), stackable=True),
                DiscountRule("BONUS_5", "FIXED", Decimal("5.00"), stackable=True),
            ),
        )
        q = calculate_invoice(c, [UsageRecord("API", 2250)], as_of=date(2026, 6, 1))
        assert q.non_stackable_discount_code == "ALPHA_10", q
        assert q.discount_total == Decimal("43.00"), q
        assert q.post_discount_subtotal == Decimal("157.00"), q

    def t_fifo_credits_and_floor():
        c = Contract(
            contract_id="c5",
            catalog=base_cat,
            credits=(
                PrepaidCredit("cred-expired", Decimal("500.00"), date(2026, 5, 31)),
                PrepaidCredit("cred-late", Decimal("150.00"), date(2026, 12, 31)),
                PrepaidCredit("cred-soon", Decimal("80.00"), date(2026, 7, 1)),
            ),
            tax_rate_pct=Decimal("10.00"),
        )
        q = calculate_invoice(c, [UsageRecord("API", 1000)], as_of=date(2026, 6, 1))
        assert q.credits_applied == Decimal("100.00"), q
        assert q.total_due == Decimal("0.00"), q
        assert len(q.remaining_credits) == 1
        assert q.remaining_credits[0] == PrepaidCredit("cred-late", Decimal("130.00"), date(2026, 12, 31))

    def t_mixed_taxable_and_exempt():
        c = Contract(contract_id="c6", catalog=base_cat, tax_rate_pct=Decimal("10.00"), tax_exempt=False)
        q = calculate_invoice(c, [UsageRecord("API", 1000), UsageRecord("PRO_SUPPORT", 4)], as_of=date(2026, 6, 1))
        assert q.net_taxable_subtotal == Decimal("100.00"), q
        assert q.tax_amount == Decimal("10.00"), q
        assert q.total_due == Decimal("210.00"), q

        c_ex = Contract(contract_id="c6b", catalog=base_cat, tax_rate_pct=Decimal("10.00"), tax_exempt=True)
        q_ex = calculate_invoice(c_ex, [UsageRecord("API", 1000)], as_of=date(2026, 6, 1))
        assert q_ex.tax_amount == Decimal("0.00")

    def t_validation_and_purity():
        c = Contract(contract_id="c7", catalog=base_cat)
        usage = [UsageRecord("API", 10)]
        c_snap = copy.deepcopy(c)
        u_snap = copy.deepcopy(usage)
        calculate_invoice(c, usage, as_of=date(2026, 6, 1))
        assert c == c_snap and usage == u_snap, "Mutated caller inputs!"

        bad_cases = [
            (c, [UsageRecord("API", -1)]),
            (c, [UsageRecord("NOPE", 5)]),
            (Contract("bad_p", base_cat, proration_days=0), []),
            (Contract("bad_p2", base_cat, billing_period_days=30, proration_days=31), []),
            (Contract("bad_m", base_cat, monthly_minimum=Decimal("-1")), []),
            (Contract("bad_t", {"X": SkuCatalogEntry("X", (VolumeTier(100, Decimal("1")), VolumeTier(50, Decimal("0.5"))))}), [UsageRecord("X", 10)]),
            (Contract("bad_t2", {"X": SkuCatalogEntry("X", (VolumeTier(None, Decimal("1")), VolumeTier(50, Decimal("0.5"))))}), [UsageRecord("X", 10)]),
            (Contract("bad_inc", {"X": SkuCatalogEntry("X", (VolumeTier(None, Decimal("1")),), included_units=-1)}), []),
            (Contract("bad_cap", base_cat, credit_cap_pct=Decimal("101")), []),
            (Contract("bad_d_cap", base_cat, discounts=(DiscountRule("D", "PCT", Decimal("10"), max_discount_amount=Decimal("-1")),)), []),
            (Contract("bad_d_dates", base_cat, discounts=(DiscountRule("D", "PCT", Decimal("10"), starts_on=date(2026, 7, 1), ends_on=date(2026, 6, 1)),)), []),
        ]
        for bc, bu in bad_cases:
            try:
                calculate_invoice(bc, bu, as_of=date(2026, 6, 1))
            except PricingValidationError:
                continue
            raise AssertionError(f"Expected PricingValidationError for {bc.contract_id}")

    def t_scale_latency():
        cat = {
            f"SKU_{i:02d}": SkuCatalogEntry(
                f"SKU_{i:02d}",
                (VolumeTier(500, Decimal("1.00")), VolumeTier(None, Decimal("0.50"))),
            )
            for i in range(20)
        }
        c = Contract(contract_id="perf", catalog=cat, tax_rate_pct=Decimal("7.50"))
        usage = [UsageRecord(f"SKU_{i % 20:02d}", 10 + i) for i in range(1000)]
        t0 = time.monotonic()
        q = calculate_invoice(c, usage, as_of=date(2026, 6, 1))
        dt_ms = (time.monotonic() - t0) * 1000.0
        assert q.total_due > Decimal("0") and dt_ms < 250.0, f"Latency={dt_ms:.1f}ms"

    def t_seat_segments_proration_and_validation():
        c = Contract(
            "c8-seats",
            base_cat,
            billing_period_days=30,
            seat_segments=(
                SeatSegment(1, Decimal("10.05"), 1, taxable=True),
                SeatSegment(1, Decimal("10.05"), 1, taxable=True),
            ),
            tax_rate_pct=Decimal("10.00"),
        )
        q = calculate_invoice(c, [UsageRecord("PRO_SUPPORT", 2)], as_of=date(2026, 6, 1))
        assert q.usage_subtotal == Decimal("50.68"), q
        assert q.net_taxable_subtotal == Decimal("0.68"), q
        assert q.tax_amount == Decimal("0.07"), q

        bad_seg = Contract("bad_seg_days", base_cat, billing_period_days=30, seat_segments=(SeatSegment(1, Decimal("10"), 20), SeatSegment(1, Decimal("10"), 11)))
        try:
            calculate_invoice(bad_seg, [], as_of=date(2026, 6, 1))
            raise AssertionError("Expected PricingValidationError for excess seat_segments days")
        except PricingValidationError:
            pass

    def t_scoped_and_threshold_discounts():
        c = Contract(
            "c9-scope",
            base_cat,
            discounts=(
                DiscountRule("BIG_ORDER_50", "PCT", Decimal("50"), stackable=False, min_subtotal=Decimal("500.00")),
                DiscountRule("EXACT_MIN_10", "FIXED", Decimal("10.00"), stackable=False, min_subtotal=Decimal("200.00")),
                DiscountRule("API_SCOPED_15", "PCT", Decimal("15"), stackable=False, target_sku="API"),
                DiscountRule("PRO_FLAT_10", "FIXED", Decimal("10.00"), stackable=True, target_sku="PRO_SUPPORT"),
            ),
        )
        q = calculate_invoice(c, [UsageRecord("API", 1000), UsageRecord("PRO_SUPPORT", 4)], as_of=date(2026, 6, 1))
        assert q.non_stackable_discount_code == "API_SCOPED_15", q
        assert q.discount_total == Decimal("25.00"), q

    def t_adjustments_and_same_day_credit():
        c = Contract(
            "c10-adj",
            base_cat,
            monthly_minimum=Decimal("300.00"),
            billing_period_days=30,
            proration_days=10,
            adjustments=(Adjustment("SLA_CREDIT", Decimal("-40.00"), taxable=True),),
            credits=(PrepaidCredit("today", Decimal("25.00"), date(2026, 6, 1)),),
        )
        q = calculate_invoice(c, [UsageRecord("API", 800)], as_of=date(2026, 6, 1))
        assert q.minimum_true_up == Decimal("60.00"), q
        assert q.gross_subtotal == Decimal("100.00"), q
        assert q.credits_applied == Decimal("25.00"), q
        assert q.total_due == Decimal("75.00"), q

    def t_included_units_and_volume_tier_mode():
        cat = {
            "EVT": SkuCatalogEntry(
                sku="EVT",
                tiers=(
                    VolumeTier(up_to=100, unit_price=Decimal("0.20")),
                    VolumeTier(up_to=None, unit_price=Decimal("0.10")),
                ),
                tier_mode="VOLUME",
                included_units=50,
            ),
        }
        # 200 usage - 50 included = 150 billable (>100 -> all 150 at 0.10 = 15.00; graduated would be 25.00)
        q = calculate_invoice(Contract("c11-vol", cat), [UsageRecord("EVT", 200)], as_of=date(2026, 6, 1))
        assert q.line_items[0].quantity == 200 and q.line_items[0].amount == Decimal("15.00"), q
        assert q.total_due == Decimal("15.00"), q
        # 50 usage - 50 included = 0 billable -> amount 0.00 still emitted
        q0 = calculate_invoice(Contract("c11-zero", cat), [UsageRecord("EVT", 50)], as_of=date(2026, 6, 1))
        assert q0.line_items[0].quantity == 50 and q0.line_items[0].amount == Decimal("0.00"), q0

    def t_discount_cap_and_tiebreak():
        # BIG_50 uncapped would be 250.00, capped at 30.00 -> FLAT_40 wins!
        c = Contract(
            "c12-cap",
            base_cat,
            discounts=(
                DiscountRule("AAA_BIG_50", "PCT", Decimal("50"), stackable=False, max_discount_amount=Decimal("30.00")),
                DiscountRule("ZZZ_FLAT_40", "FIXED", Decimal("40.00"), stackable=False),
                DiscountRule("STACK_CAP_20", "PCT", Decimal("50"), stackable=True, max_discount_amount=Decimal("20.00")),
            ),
        )
        # API=5000 -> 1000*0.10 + 4000*0.08 = 420.00 -> ZZZ_FLAT_40=40 -> 380 -> STACK_CAP_20 capped at 20 -> 360.00
        q = calculate_invoice(c, [UsageRecord("API", 5000)], as_of=date(2026, 6, 1))
        assert q.non_stackable_discount_code == "ZZZ_FLAT_40", q
        assert q.discount_total == Decimal("60.00"), q
        assert q.post_discount_subtotal == Decimal("360.00"), q

    def t_credit_cap_and_same_day_tiebreak():
        c = Contract(
            "c13-credcap",
            base_cat,
            credit_cap_pct=Decimal("40"),
            credits=(
                PrepaidCredit("cred-b", Decimal("50.00"), date(2026, 7, 1)),
                PrepaidCredit("cred-a", Decimal("50.00"), date(2026, 7, 1)),
            ),
            tax_rate_pct=Decimal("10.00"),
        )
        # gross=100.00 -> max credit 40.00 -> consumes cred-a first (10.00 left), cred-b untouched (50.00)
        q = calculate_invoice(c, [UsageRecord("API", 1000)], as_of=date(2026, 6, 1))
        assert q.credits_applied == Decimal("40.00"), q
        assert q.remaining_credits == (
            PrepaidCredit("cred-a", Decimal("10.00"), date(2026, 7, 1)),
            PrepaidCredit("cred-b", Decimal("50.00"), date(2026, 7, 1)),
        ), q
        assert q.net_taxable_subtotal == Decimal("60.00"), q
        assert q.tax_amount == Decimal("6.00"), q
        assert q.total_due == Decimal("66.00"), q

    def t_negative_taxable_adjustment_floor():
        c = Contract(
            "c14-negtax",
            base_cat,
            adjustments=(Adjustment("REBATE", Decimal("-50.00"), taxable=True),),
            tax_rate_pct=Decimal("10.00"),
        )
        # API=100 (taxable), PRO_SUPPORT=100 (non-taxable), ADJ=-50 (taxable)
        # gross = 150.00; raw_taxable_gross = 100 - 50 = 50.00
        q = calculate_invoice(c, [UsageRecord("API", 1000), UsageRecord("PRO_SUPPORT", 4)], as_of=date(2026, 6, 1))
        assert q.gross_subtotal == Decimal("150.00"), q
        assert q.net_taxable_subtotal == Decimal("50.00"), q
        assert q.tax_amount == Decimal("5.00"), q
        assert q.total_due == Decimal("155.00"), q

    check("h_graduated_and_aggregation", t_graduated_and_aggregation)
    check("h_half_up_rounding", t_half_up_rounding)
    check("h_minimum_proration_true_up", t_minimum_proration_true_up)
    check("h_discounts_tiebreak_and_stackable", t_discounts_tiebreak_and_stackable)
    check("h_fifo_credits_and_floor", t_fifo_credits_and_floor)
    check("h_mixed_taxable_and_exempt", t_mixed_taxable_and_exempt)
    check("h_validation_and_purity", t_validation_and_purity)
    check("h_seat_segments_proration_and_validation", t_seat_segments_proration_and_validation)
    check("h_scoped_and_threshold_discounts", t_scoped_and_threshold_discounts)
    check("h_adjustments_and_same_day_credit", t_adjustments_and_same_day_credit)
    check("h_included_units_and_volume_tier_mode", t_included_units_and_volume_tier_mode)
    check("h_discount_cap_and_tiebreak", t_discount_cap_and_tiebreak)
    check("h_credit_cap_and_same_day_tiebreak", t_credit_cap_and_same_day_tiebreak)
    check("h_negative_taxable_adjustment_floor", t_negative_taxable_adjustment_floor)
    check("h_scale_latency", t_scale_latency)
    return results


def run_mutation_kill_score() -> dict:
    modes = [
        "M1_flat_tier",
        "M2_expired_credit",
        "M3_wrong_non_stackable",
        "M4_negative_subtotal_credits",
        "M5_tax_non_taxable",
        "M6_negative_usage_accepted",
        "M7_bankers_rounding",
        "M8_credit_expiry_off_by_one",
        "M9_sku_discount_applied_globally",
        "M10_min_subtotal_strict_gt",
        "M11_seat_segments_combined_before_round",
        "M12_adjustments_after_minimum_true_up",
        "M13_included_units_ignored",
        "M14_volume_mode_uses_graduated",
        "M15_discount_cap_ignored_in_selection",
        "M16_discount_tiebreak_wrong_order",
        "M17_credit_fifo_same_date_tiebreak",
        "M18_credit_cap_pct_ignored",
        "M19_negative_taxable_adj_ignored_in_tax_base",
        "M20_validation_missing_bounds",
    ]
    killed = []
    survived = []
    for mode in modes:
        with tempfile.TemporaryDirectory() as tmp:
            mpath = Path(tmp)
            shutil.copytree("/workspace/tests", mpath / "tests")
            pkg = mpath / "pricing_engine"
            pkg.mkdir()
            shutil.copyfile("/workspace/pricing_engine/models.py", pkg / "models.py")
            shutil.copyfile("/workspace/pricing_engine/__init__.py", pkg / "__init__.py")
            (pkg / "calculator.py").write_text(
                f"from mutants import make_mutant\ncalculate_invoice = make_mutant({mode!r})\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = f"{mpath}:/grade_scripts"
            p = subprocess.run(
                ["/opt/skilleval-py/bin/python", "-m", "pytest", "-q"],
                cwd=str(mpath),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if p.returncode != 0:
                killed.append(mode)
            else:
                survived.append(mode)
    return {"killed": killed, "survived": survived, "total": len(modes)}


def main():
    cand = subprocess.run(
        ["/opt/skilleval-py/bin/python", "-m", "pytest", "-q"],
        cwd="/workspace",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    calc_src = Path("/workspace/pricing_engine/calculator.py").read_text(encoding="utf-8", errors="replace")
    uses_float = ("float(" in calc_src) or ("float " in calc_src)
    hidden = run_hidden_tests()
    muts = run_mutation_kill_score()

    payload = {
        "cand_tests_ok": cand.returncode == 0,
        "cand_tests_out": cand.stdout[-600:],
        "uses_float": uses_float,
        "hidden": hidden,
        "mutants": muts,
    }
    (OUT_DIR / "grade_payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
"""


def _scan_test_honesty(workspace: Path) -> dict[str, Any]:
    test_dir = workspace / "tests"
    files = sorted(p for p in test_dir.rglob("test_*.py") if p.is_file()) if test_dir.is_dir() else []
    combined = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files)
    test_count = len(re.findall(r"^\s*def\s+test_", combined, re.MULTILINE))
    mocks_calculator = bool(
        re.search(r"(?:patch|monkeypatch\.setattr)\([^)]*calculate_invoice", combined)
    )
    return {
        "test_count": test_count,
        "mocks_calculator": mocks_calculator,
        "honest": (test_count >= 12) and (not mocks_calculator),
    }


def grade(
    run_id: str,
    workspace: Path,
    deliverables: Path,
    task_dir: Path,
) -> GradeResult:
    _ = deliverables, task_dir
    if not (workspace / "pricing_engine" / "calculator.py").is_file():
        return GradeResult(
            run_id=run_id,
            task_id="G4-tdd-feature",
            status="missing_deliverable",
            gates=GateResults(
                G1_CONTRACT_BUILD=False,
                G2_CRITICAL_CORRECTNESS=False,
                G3_CRITICAL_SAFETY_RULES=False,
            ),
        )

    test_honesty = _scan_test_honesty(workspace)
    with tempfile.TemporaryDirectory(prefix="g4-grade-") as tmp:
        tdir = Path(tmp)
        s_path = tdir / "inspect_g4.py"
        s_path.write_text(CONTAINER_SCRIPT, encoding="utf-8")
        m_path = tdir / "mutants.py"
        m_path.write_text(MUTANTS_PY, encoding="utf-8")
        out_dir = tdir / "out"
        out_dir.mkdir()

        proc = run_in_sandbox(
            workspace,
            ["/opt/skilleval-py/bin/python", "/grade_scripts/inspect_g4.py"],
            extra_mounts={
                s_path: "/grade_scripts/inspect_g4.py",
                m_path: "/grade_scripts/mutants.py",
            },
            output_dir=out_dir,
            timeout=180,
            network_none=True,
        )
        payload_file = out_dir / "grade_payload.json"
        if proc.returncode != 0 or not payload_file.is_file():
            return GradeResult(
                run_id=run_id,
                task_id="G4-tdd-feature",
                status="grader_error",
                gates=GateResults(
                    G1_CONTRACT_BUILD=False,
                    G2_CRITICAL_CORRECTNESS=False,
                    G3_CRITICAL_SAFETY_RULES=False,
                ),
                error_detail=f"Sandbox inspect failed ({proc.returncode}): {proc.stderr[-600:]}",
            )
        data: dict[str, Any] = json.loads(payload_file.read_text(encoding="utf-8"))

    hidden = data.get("hidden", {})
    muts = data.get("mutants", {})
    killed_n = len(muts.get("killed") or [])
    total_m = max(1, int(muts.get("total") or 20))

    def h_ok(key: str) -> bool:
        return bool((hidden.get(key) or {}).get("passed"))

    cand_ok = bool(data.get("cand_tests_ok"))
    no_float = not bool(data.get("uses_float"))

    g1_gate = cand_ok
    g2_gate = (
        h_ok("h_graduated_and_aggregation")
        and h_ok("h_half_up_rounding")
        and h_ok("h_minimum_proration_true_up")
        and h_ok("h_discounts_tiebreak_and_stackable")
        and h_ok("h_fifo_credits_and_floor")
        and h_ok("h_mixed_taxable_and_exempt")
        and h_ok("h_seat_segments_proration_and_validation")
        and h_ok("h_scoped_and_threshold_discounts")
        and h_ok("h_adjustments_and_same_day_credit")
        and h_ok("h_validation_and_purity")
    )
    g3_gate = no_float and h_ok("h_validation_and_purity")

    checks = [
        CheckOutcome(
            id="g4_candidate_pytest_passes",
            dimension="correctness_completeness",
            critical=True,
            passed=cand_ok,
            detail=data.get("cand_tests_out", ""),
        ),
        CheckOutcome(
            id="g4_graduated_tiers_and_rounding",
            dimension="correctness_completeness",
            critical=True,
            passed=h_ok("h_graduated_and_aggregation") and h_ok("h_half_up_rounding"),
            detail=f"tiers={hidden.get('h_graduated_and_aggregation')}, round={hidden.get('h_half_up_rounding')}",
        ),
        CheckOutcome(
            id="g4_included_allowance_and_volume_mode",
            dimension="correctness_completeness",
            passed=h_ok("h_included_units_and_volume_tier_mode"),
            detail=(hidden.get("h_included_units_and_volume_tier_mode") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g4_proration_and_discounts",
            dimension="correctness_completeness",
            critical=True,
            passed=(
                h_ok("h_minimum_proration_true_up")
                and h_ok("h_discounts_tiebreak_and_stackable")
                and h_ok("h_seat_segments_proration_and_validation")
                and h_ok("h_scoped_and_threshold_discounts")
                and h_ok("h_adjustments_and_same_day_credit")
            ),
            detail=(
                f"min={hidden.get('h_minimum_proration_true_up')}, "
                f"disc={hidden.get('h_discounts_tiebreak_and_stackable')}, "
                f"seats={hidden.get('h_seat_segments_proration_and_validation')}, "
                f"scoped={hidden.get('h_scoped_and_threshold_discounts')}, "
                f"adj={hidden.get('h_adjustments_and_same_day_credit')}"
            ),
        ),
        CheckOutcome(
            id="g4_discount_caps_and_tiebreaks",
            dimension="robustness_edge_cases",
            passed=h_ok("h_discount_cap_and_tiebreak"),
            detail=(hidden.get("h_discount_cap_and_tiebreak") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g4_fifo_credits_and_tax",
            dimension="robustness_edge_cases",
            critical=True,
            passed=h_ok("h_fifo_credits_and_floor") and h_ok("h_mixed_taxable_and_exempt"),
            detail=f"cred={hidden.get('h_fifo_credits_and_floor')}, tax={hidden.get('h_mixed_taxable_and_exempt')}",
        ),
        CheckOutcome(
            id="g4_credit_cap_and_negative_taxable_adj",
            dimension="robustness_edge_cases",
            passed=h_ok("h_credit_cap_and_same_day_tiebreak") and h_ok("h_negative_taxable_adjustment_floor"),
            detail=(
                f"cap={hidden.get('h_credit_cap_and_same_day_tiebreak')}, "
                f"neg_tax={hidden.get('h_negative_taxable_adjustment_floor')}"
            ),
        ),
        CheckOutcome(
            id="g4_validation_and_immutability",
            dimension="robustness_edge_cases",
            critical=True,
            passed=h_ok("h_validation_and_purity"),
            detail=(hidden.get("h_validation_and_purity") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g4_mutation_kill_score",
            dimension="test_tdd_quality",
            passed=(killed_n >= 18),
            score_fraction=round(killed_n / total_m, 4),
            detail=f"killed={killed_n}/{total_m} {muts.get('killed')}, survived={muts.get('survived')}",
        ),
        CheckOutcome(
            id="g4_real_behavioral_tests",
            dimension="test_tdd_quality",
            passed=test_honesty["honest"],
            detail=f"test_count={test_honesty['test_count']}, mocks_calculator={test_honesty['mocks_calculator']}",
        ),
        CheckOutcome(
            id="g4_decimal_only_and_performance",
            dimension="solution_performance_security",
            critical=True,
            passed=no_float and h_ok("h_scale_latency"),
            detail=f"uses_float={data.get('uses_float')}, perf={hidden.get('h_scale_latency')}",
        ),
    ]

    return GradeResult(
        run_id=run_id,
        task_id="G4-tdd-feature",
        status="graded",
        gates=GateResults(
            G1_CONTRACT_BUILD=g1_gate,
            G2_CRITICAL_CORRECTNESS=g2_gate,
            G3_CRITICAL_SAFETY_RULES=g3_gate,
        ),
        checks=checks,
        solution_performance={
            "mutants_killed": killed_n,
            "mutants_total": total_m,
            "scale_ok": h_ok("h_scale_latency"),
        },
    )
