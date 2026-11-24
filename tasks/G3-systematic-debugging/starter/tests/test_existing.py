from billing_svc.cache import TenantPolicyCache, TenantPolicyStore
from billing_svc.currency import apply_bps, compute_tax_cents
from billing_svc.models import InvoiceTotalMismatchError, WebhookPayment
from billing_svc.pricing import generate_invoice
from billing_svc.reconciler import reconcile_payment
import pytest


def test_currency_rounding_half_up() -> None:
    assert apply_bps(105, 500) == 5  # 5.25 -> 5
    assert apply_bps(110, 500) == 6  # 5.50 -> 6 (half up)
    assert compute_tax_cents(10_000, 800) == 800


def test_single_tenant_no_promo_invoice() -> None:
    cache = TenantPolicyCache()
    inv = generate_invoice("inv-1", "tenant-solo", 3, cache=cache)
    assert inv.subtotal_cents == 30_000
    assert inv.discount_cents == 0
    assert inv.credit_cents == 0
    assert inv.tax_cents == 2_400
    assert inv.total_cents == 32_400


def test_reconciler_accepts_exact_and_rejects_mismatch() -> None:
    cache = TenantPolicyCache()
    inv = generate_invoice("inv-2", "tenant-ok", 2, cache=cache)
    ok_pay = WebhookPayment("pay-1", "inv-2", "tenant-ok", inv.total_cents)
    assert reconcile_payment(inv, ok_pay) == "reconciled"

    bad_pay = WebhookPayment("pay-2", "inv-2", "tenant-ok", inv.total_cents - 1)
    with pytest.raises(InvoiceTotalMismatchError):
        reconcile_payment(inv, bad_pay)


def test_cache_reuses_loaded_tenant_policy() -> None:
    store = TenantPolicyStore()
    cache = TenantPolicyCache(store)
    generate_invoice("inv-a", "tenant-cached", 1, cache=cache)
    generate_invoice("inv-b", "tenant-cached", 2, cache=cache)
    assert store.load_calls == 1
    assert cache.hits >= 1
