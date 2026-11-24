from billing_svc.cache import TenantPolicyCache
from billing_svc.models import WebhookPayment
from billing_svc.pricing import generate_invoice
from billing_svc.reconciler import reconcile_payment


def test_tenant_b_does_not_inherit_tenant_a_promo() -> None:
    cache = TenantPolicyCache()
    inv_a = generate_invoice("inv-a", "tenant-a", 2, promo_code="ANNUAL20", cache=cache)
    assert inv_a.discount_cents == 4_000

    # Tenant B has NO promo code; expected total is 20_000 + 8% tax = 21_600
    inv_b = generate_invoice("inv-b", "tenant-b", 2, cache=cache)
    pay_b = WebhookPayment("pay-b", "inv-b", "tenant-b", 21_600)
    assert reconcile_payment(inv_b, pay_b) == "reconciled"
