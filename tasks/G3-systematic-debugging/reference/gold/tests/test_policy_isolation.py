import copy

import pytest

from billing_svc.batch_runner import BatchRunner
from billing_svc.cache import DEFAULT_POLICY, TenantPolicyCache, TenantPolicyStore
from billing_svc.ledger import CreditLedger
from billing_svc.models import BatchItem, PricingError
from billing_svc.pricing import generate_invoice
from billing_svc.tax_engine import TaxEngine
from billing_svc.webhook import parse_batch_payload


def test_feature_credits_and_default_policy_remain_isolated() -> None:
    snap = copy.deepcopy(DEFAULT_POLICY)
    cache = TenantPolicyCache()
    inv_a = generate_invoice("inv-1", "t-a", 2, promo_code="ANNUAL20", grant_credit_cents=1_500, cache=cache)
    inv_b = generate_invoice("inv-2", "t-b", 2, cache=cache)
    assert inv_a.credit_cents == 1_500
    assert inv_b.credit_cents == 0
    assert inv_b.discount_cents == 0
    assert DEFAULT_POLICY == snap


def test_same_tenant_repeated_invoice_does_not_leak_one_time_promo_or_credit() -> None:
    store = TenantPolicyStore()
    cache = TenantPolicyCache(store)
    inv1 = generate_invoice("inv-1", "t-repeat", 3, promo_code="LAUNCH15", grant_credit_cents=2_000, cache=cache)
    inv2 = generate_invoice("inv-2", "t-repeat", 3, cache=cache)
    assert inv1.discount_cents == 4_500
    assert inv1.credit_cents == 2_000
    assert inv2.discount_cents == 0
    assert inv2.credit_cents == 0
    assert store.load_calls == 1


def test_tax_engine_quarter_and_exempt_isolation() -> None:
    engine = TaxEngine()
    inv_exempt = generate_invoice("tx-1", "t-ex", 1, country="US", quarter="2026Q1", tax_exempt=True, tax_engine=engine)
    inv_q1 = generate_invoice("tx-2", "t-q1", 1, country="US", quarter="2026Q1", tax_engine=engine)
    inv_q2 = generate_invoice("tx-3", "t-q2", 1, country="US", quarter="2026Q2", tax_engine=engine)
    assert inv_exempt.tax_cents == 0
    assert inv_q1.tax_cents == 800
    assert inv_q2.tax_cents == 825


def test_batch_runner_rolls_back_and_refunds_excess_ledger_credit() -> None:
    ledger = CreditLedger({"t-roll": 5_000, "t-cap": 5_000})
    runner = BatchRunner(ledger=ledger)
    res = runner.process_batch(
        [
            BatchItem("b-bad", "t-roll", seats=0, ledger_credit_cents=5_000),
            BatchItem("b-ok", "t-roll", seats=1, ledger_credit_cents=5_000, payment_cents=5_400),
            BatchItem("b-cap", "t-cap", seats=1, promo_code="ANNUAL20", grant_credit_cents=6_000, ledger_credit_cents=5_000, payment_cents=0),
        ]
    )
    assert res[0].status == "failed"
    assert res[1].status == "reconciled"
    assert res[1].invoice is not None and res[1].invoice.credit_cents == 5_000
    assert ledger.balance("t-roll") == 0
    assert res[2].status == "reconciled"
    assert res[2].invoice is not None and res[2].invoice.credit_cents == 8_000
    assert ledger.balance("t-cap") == 3_000


def test_batch_runner_reconciled_invoice_idempotency() -> None:
    ledger = CreditLedger({"t-idem": 10_000})
    runner = BatchRunner(ledger=ledger)
    item = BatchItem("inv-dup-1", "t-idem", seats=1, ledger_credit_cents=5_000, payment_cents=5_400)
    r1 = runner.process_batch([item, item])
    r2 = runner.process_batch([item])
    assert r1[0].status == "reconciled"
    assert r1[1] == r1[0]
    assert r2[0] == r1[0]
    assert ledger.balance("t-idem") == 5_000


def test_defense_in_depth_tenant_validation_and_webhook_normalization() -> None:
    with pytest.raises(PricingError):
        parse_batch_payload([{"invoice_id": "i-1", "tenant_id": "   ", "seats": 1}])
    parsed = parse_batch_payload([{"invoice_id": " i-2 ", "tenant_id": " t-norm ", "seats": 1, "country": " us ", "quarter": "2026q2"}])
    assert parsed[0].tenant_id == "t-norm"
    assert parsed[0].country == "US"
    assert parsed[0].quarter == "2026Q2"

    with pytest.raises(PricingError):
        TenantPolicyCache().get_policy("  ")
    with pytest.raises(PricingError):
        CreditLedger().apply_credit("", 100)
    with pytest.raises(PricingError):
        generate_invoice("i-3", "  ", 1)
