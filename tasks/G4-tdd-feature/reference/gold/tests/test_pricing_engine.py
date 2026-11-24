from datetime import date
from decimal import Decimal
import pytest

from pricing_engine.calculator import calculate_invoice
from pricing_engine.models import (
    Adjustment,
    Contract,
    DiscountRule,
    PrepaidCredit,
    PricingValidationError,
    SeatSegment,
    SkuCatalogEntry,
    UsageRecord,
    VolumeTier,
)


def _catalog() -> dict[str, SkuCatalogEntry]:
    return {
        "API": SkuCatalogEntry(
            sku="API",
            tiers=(
                VolumeTier(up_to=1000, unit_price=Decimal("0.10")),
                VolumeTier(up_to=5000, unit_price=Decimal("0.08")),
                VolumeTier(up_to=None, unit_price=Decimal("0.05")),
            ),
            taxable=True,
        ),
        "SVC": SkuCatalogEntry(
            sku="SVC",
            tiers=(VolumeTier(up_to=None, unit_price=Decimal("25.00")),),
            taxable=False,
        ),
    }


def test_graduated_volume_tiers_and_half_up_rounding() -> None:
    c = Contract("c1", _catalog(), tax_rate_pct=Decimal("5.00"))
    q = calculate_invoice(c, [UsageRecord("API", 6000)], as_of=date(2026, 6, 1))
    assert q.usage_subtotal == Decimal("470.00")

    cat = {"ODD": SkuCatalogEntry("ODD", (VolumeTier(None, Decimal("1.005")),))}
    q2 = calculate_invoice(Contract("c-half", cat, tax_rate_pct=Decimal("5.00")), [UsageRecord("ODD", 5)], as_of=date(2026, 6, 1))
    assert q2.usage_subtotal == Decimal("5.03")
    assert q2.tax_amount == Decimal("0.25")


def test_included_allowance_and_volume_tier_mode() -> None:
    cat = {
        "EVT": SkuCatalogEntry(
            sku="EVT",
            tiers=(
                VolumeTier(up_to=100, unit_price=Decimal("0.20")),
                VolumeTier(up_to=None, unit_price=Decimal("0.10")),
            ),
            tier_mode="VOLUME",
            included_units=50,
        )
    }
    q = calculate_invoice(Contract("c-vol", cat), [UsageRecord("EVT", 200)], as_of=date(2026, 6, 1))
    assert q.line_items[0].quantity == 200
    assert q.line_items[0].amount == Decimal("15.00")

    q_zero = calculate_invoice(Contract("c-zero", cat), [UsageRecord("EVT", 50)], as_of=date(2026, 6, 1))
    assert q_zero.line_items[0].quantity == 50
    assert q_zero.line_items[0].amount == Decimal("0.00")


def test_prorated_minimum_and_credit_note_adjustment_before_minimum() -> None:
    c = Contract(
        "c2",
        _catalog(),
        monthly_minimum=Decimal("300.00"),
        billing_period_days=30,
        proration_days=10,
        adjustments=(Adjustment("SLA_CREDIT", Decimal("-40.00")),),
    )
    q = calculate_invoice(c, [UsageRecord("API", 800)], as_of=date(2026, 6, 1))
    assert q.minimum_true_up == Decimal("60.00")
    assert q.gross_subtotal == Decimal("100.00")


def test_non_stackable_tie_break_target_sku_and_min_subtotal() -> None:
    c = Contract(
        "c3",
        _catalog(),
        discounts=(
            DiscountRule("MIN_BLOCKED", "PCT", Decimal("50"), stackable=False, min_subtotal=Decimal("500.00")),
            DiscountRule("MIN_EXACT", "FIXED", Decimal("15.00"), stackable=False, min_subtotal=Decimal("200.00")),
            DiscountRule("API_SCOPED_15", "PCT", Decimal("15"), stackable=False, target_sku="API"),
            DiscountRule("ZETA_10", "PCT", Decimal("10"), stackable=False),
            DiscountRule("BETA_20", "FIXED", Decimal("20.00"), stackable=False),
            DiscountRule("ALPHA_10", "PCT", Decimal("10"), stackable=False),
            DiscountRule("SVC_FLAT_10", "FIXED", Decimal("10.00"), stackable=True, target_sku="SVC"),
        ),
    )
    q = calculate_invoice(c, [UsageRecord("API", 1000), UsageRecord("SVC", 4)], as_of=date(2026, 6, 1))
    assert q.non_stackable_discount_code == "ALPHA_10"
    assert q.discount_total == Decimal("30.00")

    c_exact = Contract(
        "c3-exact",
        _catalog(),
        discounts=(
            DiscountRule("MIN_EXACT_25", "FIXED", Decimal("25.00"), stackable=False, min_subtotal=Decimal("200.00")),
            DiscountRule("API_SCOPED_22", "PCT", Decimal("22"), stackable=False, target_sku="API"),
        ),
    )
    q2 = calculate_invoice(c_exact, [UsageRecord("API", 1000), UsageRecord("SVC", 4)], as_of=date(2026, 6, 1))
    assert q2.non_stackable_discount_code == "MIN_EXACT_25"
    assert q2.discount_total == Decimal("25.00")


def test_discount_max_discount_amount_cap_selection() -> None:
    c = Contract(
        "c3-cap",
        _catalog(),
        discounts=(
            DiscountRule("AAA_PCT_50", "PCT", Decimal("50"), stackable=False, max_discount_amount=Decimal("25.00")),
            DiscountRule("BBB_FIXED_35", "FIXED", Decimal("35.00"), stackable=False),
            DiscountRule("STACK_CAP_10", "PCT", Decimal("50"), stackable=True, max_discount_amount=Decimal("10.00")),
        ),
    )
    q = calculate_invoice(c, [UsageRecord("API", 1000)], as_of=date(2026, 6, 1))
    assert q.non_stackable_discount_code == "BBB_FIXED_35"
    assert q.discount_total == Decimal("45.00")
    assert q.post_discount_subtotal == Decimal("55.00")


def test_expired_and_same_day_fifo_credits_and_floor() -> None:
    c = Contract(
        "c4",
        _catalog(),
        credits=(
            PrepaidCredit("old", Decimal("500.00"), date(2026, 5, 31)),
            PrepaidCredit("today", Decimal("40.00"), date(2026, 6, 1)),
            PrepaidCredit("later", Decimal("100.00"), date(2026, 9, 1)),
        ),
    )
    q = calculate_invoice(c, [UsageRecord("API", 1000)], as_of=date(2026, 6, 1))
    assert q.credits_applied == Decimal("100.00")
    assert q.total_due == Decimal("0.00")
    assert q.remaining_credits == (PrepaidCredit("later", Decimal("40.00"), date(2026, 9, 1)),)


def test_credit_cap_pct_and_same_date_fifo_tiebreak() -> None:
    c = Contract(
        "c4-cap",
        _catalog(),
        credit_cap_pct=Decimal("40"),
        credits=(
            PrepaidCredit("cred-z", Decimal("50.00"), date(2026, 7, 1)),
            PrepaidCredit("cred-a", Decimal("50.00"), date(2026, 7, 1)),
        ),
        tax_rate_pct=Decimal("10.00"),
    )
    q = calculate_invoice(c, [UsageRecord("API", 1000)], as_of=date(2026, 6, 1))
    assert q.credits_applied == Decimal("40.00")
    assert q.remaining_credits == (
        PrepaidCredit("cred-a", Decimal("10.00"), date(2026, 7, 1)),
        PrepaidCredit("cred-z", Decimal("50.00"), date(2026, 7, 1)),
    )
    assert q.total_due == Decimal("66.00")


def test_excess_credits_never_drive_subtotal_negative() -> None:
    c = Contract(
        "c4-floor",
        _catalog(),
        credits=(PrepaidCredit("big", Decimal("300.00"), date(2026, 8, 1)),),
    )
    q = calculate_invoice(c, [UsageRecord("API", 1000)], as_of=date(2026, 6, 1))
    assert q.credits_applied == Decimal("100.00")
    assert q.total_due == Decimal("0.00")
    assert q.remaining_credits == (PrepaidCredit("big", Decimal("200.00"), date(2026, 8, 1)),)


def test_seat_segments_per_segment_rounding_and_non_taxable_exclusion() -> None:
    c = Contract(
        "c5",
        _catalog(),
        billing_period_days=30,
        seat_segments=(
            SeatSegment(seats=1, monthly_seat_price=Decimal("10.05"), active_days=1, taxable=True),
            SeatSegment(seats=1, monthly_seat_price=Decimal("10.05"), active_days=1, taxable=True),
        ),
        tax_rate_pct=Decimal("10.00"),
    )
    q = calculate_invoice(c, [UsageRecord("SVC", 2)], as_of=date(2026, 6, 1))
    assert q.usage_subtotal == Decimal("50.68")
    assert q.net_taxable_subtotal == Decimal("0.68")
    assert q.tax_amount == Decimal("0.07")


def test_negative_taxable_adjustment_reduces_tax_base() -> None:
    c = Contract(
        "c5-negadj",
        _catalog(),
        adjustments=(Adjustment("CREDIT_NOTE", Decimal("-50.00"), taxable=True),),
        tax_rate_pct=Decimal("10.00"),
    )
    q = calculate_invoice(c, [UsageRecord("API", 1000), UsageRecord("SVC", 4)], as_of=date(2026, 6, 1))
    assert q.gross_subtotal == Decimal("150.00")
    assert q.net_taxable_subtotal == Decimal("50.00")
    assert q.tax_amount == Decimal("5.00")
    assert q.total_due == Decimal("155.00")


def test_validation_errors_negative_usage_and_excess_seat_days() -> None:
    c = Contract("c6", _catalog())
    with pytest.raises(PricingValidationError):
        calculate_invoice(c, [UsageRecord("API", -5)], as_of=date(2026, 6, 1))

    c_bad_seats = Contract(
        "c7",
        _catalog(),
        billing_period_days=30,
        seat_segments=(SeatSegment(1, Decimal("10.00"), 20), SeatSegment(1, Decimal("10.00"), 11)),
    )
    with pytest.raises(PricingValidationError):
        calculate_invoice(c_bad_seats, [], as_of=date(2026, 6, 1))


def test_validation_errors_new_spec_bounds() -> None:
    with pytest.raises(PricingValidationError):
        calculate_invoice(Contract("b1", _catalog(), credit_cap_pct=Decimal("101")), [], as_of=date(2026, 6, 1))
    with pytest.raises(PricingValidationError):
        calculate_invoice(
            Contract("b2", {"X": SkuCatalogEntry("X", (VolumeTier(None, Decimal("1")),), included_units=-1)}),
            [],
            as_of=date(2026, 6, 1),
        )
    with pytest.raises(PricingValidationError):
        calculate_invoice(
            Contract("b3", _catalog(), discounts=(DiscountRule("D", "PCT", Decimal("10"), max_discount_amount=Decimal("-1")),)),
            [],
            as_of=date(2026, 6, 1),
        )
    with pytest.raises(PricingValidationError):
        calculate_invoice(
            Contract("b4", _catalog(), discounts=(DiscountRule("D", "PCT", Decimal("10"), starts_on=date(2026, 7, 1), ends_on=date(2026, 6, 1)),)),
            [],
            as_of=date(2026, 6, 1),
        )
